import React, { useState } from 'react';
import CodeBlock from '@theme/CodeBlock';

export default function EnhancedCodeBlock({ children, language, title, showRunButton = false }) {
  const [copied, setCopied] = useState(false);

  const copyToClipboard = () => {
    navigator.clipboard.writeText(children);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="enhanced-code-block">
      {(title || showRunButton) && (
        <div className="code-block-header">
          {title && <span className="code-block-title">{title}</span>}
          <div className="code-block-actions">
            <button
              className="code-block-copy"
              onClick={copyToClipboard}
              title="Copy code"
            >
              {copied ? '✓ Copied' : '📋 Copy'}
            </button>
          </div>
        </div>
      )}
      <CodeBlock language={language}>{children}</CodeBlock>
      <style>{`
        .enhanced-code-block {
          margin: 1rem 0;
        }
        .code-block-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 0.5rem 1rem;
          background: var(--ifm-color-emphasis-100);
          border-top-left-radius: var(--ifm-code-border-radius);
          border-top-right-radius: var(--ifm-code-border-radius);
          border-bottom: 1px solid var(--ifm-color-emphasis-200);
        }
        .code-block-title {
          font-weight: 600;
          font-size: 0.9rem;
        }
        .code-block-copy {
          background: var(--ifm-color-primary);
          color: white;
          border: none;
          padding: 0.25rem 0.75rem;
          border-radius: 4px;
          cursor: pointer;
          font-size: 0.85rem;
          transition: opacity 0.2s;
        }
        .code-block-copy:hover {
          opacity: 0.9;
        }
      `}</style>
    </div>
  );
}
