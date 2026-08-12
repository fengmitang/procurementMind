// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { describe, expect, it } from 'vitest'
import { StatusTag } from './StatusTag'

describe('StatusTag', () => {
  it('renders the Chinese business label', () => {
    render(<StatusTag status="PENDING_REVIEW" />)
    expect(screen.getByText('待审批')).toBeInTheDocument()
  })
})
