import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ListingResultView } from '@/components/features/ListingResult';
import type { ListingResult } from '@/types';

const sampleResult = (overrides: Partial<ListingResult> = {}): ListingResult => ({
  product_id: 'prod-1',
  title: 'Sample Title',
  bullets: ['First bullet', 'Second bullet'],
  description: 'Sample description',
  keywords: ['alpha', 'beta'],
  tokens_used: 12,
  ...overrides,
});

describe('ListingResultView copy buttons', () => {
  const writeText = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    writeText.mockClear();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('copies title, bullets, and description independently and switches icon feedback', async () => {
    render(<ListingResultView result={sampleResult()} />);

    const buttons = screen.getAllByTitle('Copy');
    expect(buttons).toHaveLength(4);

    fireEvent.click(buttons[0]);
    await waitFor(() => {
      expect(writeText).toHaveBeenLastCalledWith('Sample Title');
    });
    expect(buttons[0].querySelector('.text-green-500')).not.toBeNull();
    expect(buttons[1].querySelector('.text-green-500')).toBeNull();

    fireEvent.click(buttons[1]);
    await waitFor(() => {
      expect(writeText).toHaveBeenLastCalledWith('First bullet');
    });
    expect(buttons[1].querySelector('.text-green-500')).not.toBeNull();
    expect(buttons[0].querySelector('.text-green-500')).toBeNull();

    fireEvent.click(buttons[3]);
    await waitFor(() => {
      expect(writeText).toHaveBeenLastCalledWith('Sample description');
    });
    expect(buttons[3].querySelector('.text-green-500')).not.toBeNull();
  });

  it('keeps copy behavior after rerender with updated listing fields', async () => {
    const { rerender } = render(<ListingResultView result={sampleResult()} />);

    fireEvent.click(screen.getAllByTitle('Copy')[0]);
    await waitFor(() => {
      expect(writeText).toHaveBeenLastCalledWith('Sample Title');
    });

    rerender(<ListingResultView result={sampleResult({ title: 'Updated Title' })} />);

    const buttons = screen.getAllByTitle('Copy');
    fireEvent.click(buttons[0]);
    await waitFor(() => {
      expect(writeText).toHaveBeenLastCalledWith('Updated Title');
    });
    expect(buttons[0].querySelector('.text-green-500')).not.toBeNull();
  });
});
