import { describe, expect, it } from 'vitest'
import { RECOMMENDATION_QUICK_MESSAGE } from './assistant'

describe('recommendation quick action', () => {
  it('sends an explicit recommendation intent through chat', () => {
    expect(RECOMMENDATION_QUICK_MESSAGE).toContain('推荐')
    expect(RECOMMENDATION_QUICK_MESSAGE).toContain('历史')
  })
})
