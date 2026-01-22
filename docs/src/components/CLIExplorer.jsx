import React, { useState, useMemo } from 'react';
import clsx from 'clsx';

// CLI commands data structure
const cliCommands = [
  {
    command: 'accounts',
    description: 'Manage Telegram accounts',
    subcommands: [
      { cmd: '--import', desc: 'Import accounts from gen_config.py' },
      { cmd: '--list', desc: 'List configured accounts and their status' },
      { cmd: '--test', desc: 'Test all accounts for connectivity' },
      { cmd: '--reset', desc: 'Reset account usage statistics' },
    ],
  },
  {
    command: 'discover',
    description: 'Discover groups and channels',
    subcommands: [
      { cmd: '--seed', desc: 'Discover groups from a seed entity' },
      { cmd: '--seeds-file', desc: 'Discover from multiple seeds in a file' },
      { cmd: '--crawler-dir', desc: 'Import existing scan data' },
      { cmd: '--depth', desc: 'Set discovery depth' },
    ],
  },
  {
    command: 'network',
    description: 'Analyze network relationships',
    subcommands: [
      { cmd: '--crawler-dir', desc: 'Analyze network from crawler data' },
      { cmd: '--from-db', desc: 'Analyze network from SQL database' },
      { cmd: '--plot', desc: 'Generate network plot' },
      { cmd: '--export', desc: 'Export results to file' },
    ],
  },
  {
    command: 'archive',
    description: 'Archive messages and media',
    subcommands: [
      { cmd: '--entity', desc: 'Archive a specific channel or group' },
      { cmd: '--date-range', desc: 'Specify date range for archiving' },
    ],
  },
  {
    command: 'forward',
    description: 'Forward messages between channels',
    subcommands: [
      { cmd: '--origin', desc: 'Source channel or chat' },
      { cmd: '--destination', desc: 'Target channel or chat' },
      { cmd: '--total-mode', desc: 'Forward from all accessible channels' },
      { cmd: '--enable-deduplication', desc: 'Enable duplicate detection' },
    ],
  },
];

export default function CLIExplorer() {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCommand, setSelectedCommand] = useState(null);

  const filteredCommands = useMemo(() => {
    if (!searchTerm) return cliCommands;
    const term = searchTerm.toLowerCase();
    return cliCommands.filter(
      (cmd) =>
        cmd.command.toLowerCase().includes(term) ||
        cmd.description.toLowerCase().includes(term) ||
        cmd.subcommands.some((sub) =>
          sub.cmd.toLowerCase().includes(term) ||
          sub.desc.toLowerCase().includes(term)
        )
    );
  }, [searchTerm]);

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    // Could add a toast notification here
  };

  return (
    <div className="cli-explorer">
      <div className="cli-search">
        <input
          type="text"
          placeholder="Search CLI commands..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="cli-search-input"
        />
      </div>

      <div className="cli-commands">
        {filteredCommands.map((cmd) => (
          <div key={cmd.command} className="cli-command-card">
            <div
              className="cli-command-header"
              onClick={() =>
                setSelectedCommand(
                  selectedCommand === cmd.command ? null : cmd.command
                )
              }
            >
              <code className="cli-command-name">
                python -m tgarchive {cmd.command}
              </code>
              <button
                className="cli-copy-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  copyToClipboard(`python -m tgarchive ${cmd.command}`);
                }}
                title="Copy command"
              >
                📋
              </button>
            </div>
            <p className="cli-command-desc">{cmd.description}</p>
            {selectedCommand === cmd.command && (
              <div className="cli-subcommands">
                <h4>Options:</h4>
                {cmd.subcommands.map((sub, idx) => (
                  <div key={idx} className="cli-subcommand">
                    <code>{sub.cmd}</code>
                    <span>{sub.desc}</span>
                    <button
                      className="cli-copy-btn-small"
                      onClick={() =>
                        copyToClipboard(
                          `python -m tgarchive ${cmd.command} ${sub.cmd}`
                        )
                      }
                      title="Copy full command"
                    >
                      📋
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <style>{`
        .cli-explorer {
          margin: 2rem 0;
        }
        .cli-search-input {
          width: 100%;
          padding: 0.75rem;
          border: 1px solid var(--ifm-color-emphasis-300);
          border-radius: 4px;
          font-size: 1rem;
        }
        .cli-commands {
          margin-top: 1rem;
        }
        .cli-command-card {
          border: 1px solid var(--ifm-color-emphasis-200);
          border-radius: 8px;
          padding: 1rem;
          margin-bottom: 1rem;
          background: var(--ifm-background-surface-color);
        }
        .cli-command-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          cursor: pointer;
        }
        .cli-command-name {
          font-size: 1.1rem;
          font-weight: 600;
          color: var(--ifm-color-primary);
        }
        .cli-command-desc {
          margin: 0.5rem 0;
          color: var(--ifm-color-content-secondary);
        }
        .cli-subcommands {
          margin-top: 1rem;
          padding-top: 1rem;
          border-top: 1px solid var(--ifm-color-emphasis-200);
        }
        .cli-subcommand {
          display: flex;
          align-items: center;
          gap: 1rem;
          padding: 0.5rem;
          margin: 0.25rem 0;
        }
        .cli-subcommand code {
          background: var(--ifm-code-background);
          padding: 0.25rem 0.5rem;
          border-radius: 4px;
          font-size: 0.9rem;
        }
        .cli-copy-btn,
        .cli-copy-btn-small {
          background: none;
          border: none;
          cursor: pointer;
          font-size: 1rem;
          opacity: 0.7;
          transition: opacity 0.2s;
        }
        .cli-copy-btn:hover,
        .cli-copy-btn-small:hover {
          opacity: 1;
        }
        .cli-copy-btn-small {
          font-size: 0.8rem;
        }
      `}</style>
    </div>
  );
}
