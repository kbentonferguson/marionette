import { expect, it } from 'vitest';
import { streamErrorText } from '../components/conversation/streamTerminal';

it.each(['input_commit_uncertain', 'input_delivery_uncertain', 'input_stop_uncertain'])('keeps %s uncertainty visible on browser and native streams', code => {
  const browser = Object.assign(new Error('private body'), { status: 503, body: { code, error: 'private path' } });
  const native = { status: 503, code, message: 'private path' };
  for (const error of [browser, native]) {
    const copy = streamErrorText(error);
    expect(copy).toContain('could not be confirmed');
    expect(copy).toContain('Inspect Saved inputs');
    expect(copy).not.toContain('private');
    expect(copy).not.toContain('Send again to retry');
  }
});

it('distinguishes an attachment limit from a broken backend without echoing body text', () => {
  expect(streamErrorText({ status: 409, code: 'input_stopped', message: 'private' }))
    .toBe('[error] Stop cancelled this input. Inspect Saved inputs and your draft before sending again.');
  expect(streamErrorText({ status: 503, code: 'input_attachment_limit', message: 'private' }))
    .toBe('[error] Attachment limits exceeded. Reduce the attachments in your draft before sending.');
  expect(streamErrorText({ status: 503, code: 'backend_error' })).toContain('backend request failed');
});
