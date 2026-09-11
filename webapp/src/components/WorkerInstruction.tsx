import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { classifyTranscriptHref, openAgentLink } from '../lib/agentLinks';

export default function WorkerInstruction({ text, truncated = false }: { text: string; truncated?: boolean }) {
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  return <div className="swarm-instruction-reader">
    <div className="swarm-instruction-tools">
      <span>Task brief{truncated ? ' · partial' : ''}</span>
      <button type="button" aria-label="Copy instruction" disabled={!text} onClick={() => {
        void navigator.clipboard.writeText(text).then(() => setCopyState('copied'), () => setCopyState('failed'));
      }}>{copyState === 'copied' ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
        <span role="status">{copyState === 'copied' ? 'Copied' : copyState === 'failed' ? 'Copy failed' : 'Copy'}</span>
      </button>
    </div>
    <div className="swarm-instruction-prose" role="region" aria-label="Worker instruction" tabIndex={0}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
        a: ({ href, children }) => !href || classifyTranscriptHref(href) === 'none'
          ? <span>{children}</span>
          : <a href={href} onClick={event => openAgentLink(href, event)}>{children}</a>,
        img: ({ alt }) => <span>{alt || 'Image reference'}</span>,
      }}>{text || 'Instruction unavailable.'}</ReactMarkdown>
    </div>
    {truncated && <p className="swarm-instruction-note">The source supplied a partial instruction.</p>}
  </div>;
}
