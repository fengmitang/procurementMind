import socket
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

import pytest
import uvicorn

from agent_app.core.config import AgentSettings
from agent_app.graph.schemas import GraphRunRequest, RouteType
from agent_app.graph.service import ProcurementGraphService
from agent_app.schemas.backend import BackendIdentity, CurrentUserData
from app.core.config import get_settings
from app.db.session import engine
from app.main import app as backend_app
from scripts.seed_demo_data import seed_demo_data


@contextmanager
def live_backend_url():
    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen_socket.bind(("127.0.0.1", 0))
    listen_socket.listen(128)
    port = listen_socket.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            backend_app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
        )
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listen_socket]},
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        listen_socket.close()
        raise RuntimeError("真实采购后端测试服务启动失败")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listen_socket.close()


@pytest.mark.asyncio
async def test_graph_mcp_chain_reads_facts_from_real_backend() -> None:
    await seed_demo_data()
    await engine.dispose()
    backend_settings = get_settings()
    identity = BackendIdentity(
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-01",
    )
    current_user = CurrentUserData(
        employee_id=90001,
        employee_no="TEST-E001",
        name="测试需求人",
        mobile="13800009001",
        status="ACTIVE",
        platform_type=identity.platform_type,
        platform_user_id=identity.platform_user_id,
        roles=[],
        buildings=[],
    )
    try:
        with live_backend_url() as backend_url:
            settings = AgentSettings(
                _env_file=None,
                identity_gateway_secret=backend_settings.identity_gateway_secret,
                procurement_backend_url=backend_url,
                procurement_backend_max_retries=0,
                mcp_startup_timeout_seconds=60,
            )
            result = await ProcurementGraphService(settings).run(
                GraphRunRequest(
                    task_id=uuid4(),
                    trace_id="trace-graph-real-backend",
                    conversation_id=1,
                    identity=identity,
                    current_user=current_user,
                    message="查询采购申请 91007 当前状态和下一处理人",
                )
            )
            admin_identity = BackendIdentity(
                platform_type="TEST_PLATFORM",
                platform_user_id="test-user-05",
            )
            analysis_result = await ProcurementGraphService(settings).run(
                GraphRunRequest(
                    task_id=uuid4(),
                    trace_id="trace-analysis-real-backend",
                    conversation_id=2,
                    identity=admin_identity,
                    current_user=current_user.model_copy(
                        update={
                            "employee_id": 90005,
                            "name": "测试系统管理员",
                            "platform_user_id": "test-user-05",
                        }
                    ),
                    message=(
                        "统计 2026-08-01 到 2026-08-05 算力服务器各品牌采购数量、"
                        "平均单价、中位价和总金额"
                    ),
                )
            )
            risk_result = await ProcurementGraphService(settings).run(
                GraphRunRequest(
                    task_id=uuid4(),
                    trace_id="trace-risk-real-backend",
                    conversation_id=3,
                    identity=identity,
                    current_user=current_user,
                    message="调查采购申请 91009 的审批风险",
                )
            )
    finally:
        await engine.dispose()

    assert result.route is RouteType.REALTIME_BUSINESS
    assert result.errors == []
    assert result.tool_results[0].success is True
    assert result.tool_results[0].trace_id == "trace-graph-real-backend"
    assert result.evidence[0].data["requirement_no"] == "TEST-PR-COMPLETED-EQUAL"
    assert result.evidence[0].data["status"] == "COMPLETED"
    assert "COMPLETED" in result.reply
    assert analysis_result.route is RouteType.COMPLEX_QUERY
    assert analysis_result.errors == []
    assert analysis_result.analysis is not None
    assert analysis_result.analysis.summary == {
        "count": 9,
        "average_unit_price": "1112.50",
        "median_unit_price": "950.00",
        "total_amount": "34350.00",
    }
    assert analysis_result.analysis.groups[0]["key"] == "TEST-BRAND"
    assert analysis_result.tool_results[0].trace_id == "trace-analysis-real-backend"
    assert risk_result.route is RouteType.RISK_INVESTIGATION
    assert risk_result.errors == []
    assert risk_result.risk_investigation is not None
    assert risk_result.risk_investigation.review.passed is True
    assert risk_result.risk_investigation.complete is False
    assert risk_result.risk_investigation.knowledge_evidence_available is False
    assert "PRICE_DEVIATION" in {
        item.risk_code for item in risk_result.risk_investigation.summary_items
    }
    assert risk_result.tool_call_count >= 4
    assert all(result.trace_id == "trace-risk-real-backend" for result in risk_result.tool_results)
