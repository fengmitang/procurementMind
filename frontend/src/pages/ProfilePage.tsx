import { Avatar, Card, Descriptions, Tag, Typography } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import { PageShell } from '../components/PageShell'
import { useIdentity } from '../features/identity/IdentityProvider'
import { StatusTag } from '../components/StatusTag'

export function ProfilePage(){const{user}=useIdentity();return <PageShell title="个人信息" description="身份信息来自当前 Backend，不提供无后端支撑的账号编辑能力"><Card className="profile-card"><div className="profile-summary"><Avatar size={72} icon={<UserOutlined/>}/><div><Typography.Title level={3}>{user.name}</Typography.Title><Typography.Text type="secondary">{user.employee_no||`员工 #${user.employee_id}`}</Typography.Text></div></div><Descriptions bordered column={{xs:1,md:2}} items={[
  {key:'name',label:'姓名',children:user.name},{key:'mobile',label:'手机号',children:user.mobile||'—'},{key:'roles',label:'当前角色',children:user.roles.map((r)=><Tag color="blue" key={r.role_id}>{r.role_name}</Tag>)},{key:'buildings',label:'所属楼宇',children:user.buildings.length?user.buildings.map((b)=><Tag key={b.building_id}>{b.building_name}{b.is_primary?' · 主':''}</Tag>):'未绑定楼宇'},{key:'platform',label:'平台身份',children:`${user.platform_type} / ${user.platform_user_id}`},{key:'status',label:'账号状态',children:<StatusTag status={user.status}/>},]}/></Card></PageShell>}
