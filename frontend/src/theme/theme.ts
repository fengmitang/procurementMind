import type { ThemeConfig } from 'antd'

export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#1677FF', colorInfo: '#1677FF', colorSuccess: '#19A974', colorWarning: '#F59E0B',
    colorError: '#E5484D', colorText: '#17324D', colorTextSecondary: '#69829A', colorBorder: '#DCE8F5',
    colorBgLayout: '#F4F8FF', colorBgContainer: '#FFFFFF', borderRadius: 10, borderRadiusLG: 16,
    boxShadowSecondary: '0 8px 28px rgba(35, 94, 152, 0.08)', fontFamily: "Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif",
  },
  components: {
    Layout: { bodyBg: '#F4F8FF', siderBg: '#FFFFFF', headerBg: '#FFFFFF' },
    Menu: { itemBg: 'transparent', itemSelectedBg: '#EAF3FF', itemSelectedColor: '#1677FF', itemBorderRadius: 10 },
    Card: { headerBg: '#FFFFFF' }, Table: { headerBg: '#F6FAFF', headerColor: '#49657E' }, Button: { borderRadius: 9 },
  },
}
