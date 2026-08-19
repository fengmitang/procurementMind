import { describe, expect, it } from 'vitest'
import { isPositiveIntegerQuantity } from './quantity'

describe('isPositiveIntegerQuantity', () => {
  it.each([1, 2, 100, '12'])("accepts %s", (value) => {
    expect(isPositiveIntegerQuantity(value)).toBe(true)
  })

  it.each([0, -1, 2.5, '1.5', null, undefined, ''])("rejects %s", (value) => {
    expect(isPositiveIntegerQuantity(value)).toBe(false)
  })
})
