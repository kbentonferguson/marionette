import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import WorkerInstruction from '../components/WorkerInstruction';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('renders structured instructions and copies the original source unchanged', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('navigator', { clipboard: { writeText } });
  const text = '## Verify the change\n\nKeep **all five workers** visible.\n\n- Read the actual models.\n- Check partial coverage.\n\n```sh\npython -m pytest tests/test_swarm_metadata_handoff.py\n```';
  render(<WorkerInstruction text={text} truncated />);
  expect(screen.getByRole('heading', { name: 'Verify the change' })).toBeVisible();
  expect(screen.getAllByRole('listitem')).toHaveLength(2);
  expect(screen.getByText('all five workers').tagName).toBe('STRONG');
  expect(screen.getByRole('region', { name: 'Worker instruction' })).toHaveAttribute('tabindex', '0');
  expect(screen.getByText('The source supplied a partial instruction.')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Copy instruction' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Copied'));
  expect(writeText).toHaveBeenCalledWith(text);
});
