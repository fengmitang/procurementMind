// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BackendClient } from '../../services/backendClient'
import { demoIdentities } from './IdentityProvider'

afterEach(() => vi.restoreAllMocks())

describe('development identity catalog', () => {
  it('contains all core Full Demo identities and keeps Legacy TEST identities', () => {
    const ids = demoIdentities.map((identity) => identity.id)

    expect(ids).toEqual(expect.arrayContaining([
      'demo_user_001', 'demo_user_002', 'demo_user_003', 'demo_user_004',
      'demo_user_005', 'demo_user_006', 'demo_user_007', 'demo_user_008',
      'test-user-01', 'test-user-02', 'test-user-03', 'test-user-04',
      'test-user-05', 'test-user-07',
    ]))
    expect(demoIdentities.find((identity) => identity.id === 'demo_user_006')?.label)
      .toBe('演示需求人兼楼长')
  })

  it('does not store trusted roles on identity options', () => {
    expect(demoIdentities.every((identity) => !('role' in identity))).toBe(true)
  })

  it('sends the selected Demo user id through BackendClient', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      success: true,
      data: { roles: [{ role_code: 'APPLICANT' }, { role_code: 'BUILDING_MANAGER' }] },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    await new BackendClient(() => 'demo_user_006').me()

    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))
    expect(body.platform_user_id).toBe('demo_user_006')
    expect(body).not.toHaveProperty('platform_type')
  })
})
