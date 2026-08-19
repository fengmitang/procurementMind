export const POSITIVE_INTEGER_QUANTITY_MESSAGE = '设备采购数量必须为正整数。'

export function isPositiveIntegerQuantity(value: unknown): boolean {
  if (value == null || value === '') return false
  const numberValue = typeof value === 'number' ? value : Number(value)
  return Number.isInteger(numberValue) && numberValue > 0
}

export function validatePositiveIntegerQuantity(value: unknown): Promise<void> {
  return isPositiveIntegerQuantity(value)
    ? Promise.resolve()
    : Promise.reject(new Error(POSITIVE_INTEGER_QUANTITY_MESSAGE))
}
