from collections import Counter

from fastapi.routing import APIRoute, Dependant

from app.main import app


def dependency_names(dependant: Dependant) -> set[str]:
    names = {
        dependency.call.__name__
        for dependency in dependant.dependencies
        if dependency.call is not None
    }
    for dependency in dependant.dependencies:
        names.update(dependency_names(dependency))
    return names


def flatten_api_routes(routes) -> list[APIRoute]:
    flattened = []
    for route in routes:
        if isinstance(route, APIRoute):
            flattened.append(route)
        elif hasattr(route, "original_router"):
            flattened.extend(flatten_api_routes(route.original_router.routes))
    return flattened


def test_openapi_has_unique_operations_and_all_documented_core_paths() -> None:
    specification = app.openapi()
    operations = [
        operation
        for path_item in specification["paths"].values()
        for method, operation in path_item.items()
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    ]
    operation_ids = [operation["operationId"] for operation in operations]
    assert [
        operation_id for operation_id, count in Counter(operation_ids).items() if count > 1
    ] == []

    expected_paths = {
        "/api/v1/users/me",
        "/api/v1/requirements",
        "/api/v1/requirements/{requirement_id}",
        "/api/v1/requirements/{requirement_id}/timeline",
        "/api/v1/requirements/{requirement_id}/timeline/{log_id}/contact",
        "/api/v1/purchase-records",
        "/api/v1/suppliers",
        "/api/v1/recommendations/products",
        "/api/v1/agent/conversations/active",
        "/api/v1/agent/conversations/{conversation_id}/messages",
        "/api/v1/agent/conversations/{conversation_id}/state",
        "/api/v1/notifications",
        "/api/v1/notifications/dispatch-due",
        "/health",
        "/ready",
    }
    assert expected_paths <= set(specification["paths"])


def test_every_business_api_route_requires_signed_current_user() -> None:
    business_routes = [
        route for route in flatten_api_routes(app.routes) if route.path.startswith("/api/v1/")
    ]
    assert business_routes
    for route in business_routes:
        assert "get_current_user" in dependency_names(route.dependant), route.path
        assert route.response_model is not None, route.path
        assert route.response_model.__name__.startswith("ApiResponse"), route.path
