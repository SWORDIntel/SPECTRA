import React from 'react';

export default function ThreatScoreViz({ score, breakdown }) {
  const getScoreColor = (score) => {
    if (score <= 2) return '#4CAF50'; // Green - Harmless
    if (score <= 4) return '#8BC34A'; // Light Green - Low Risk
    if (score <= 6) return '#FFC107'; // Yellow - Medium
    if (score <= 8) return '#FF9800'; // Orange - High Risk
    return '#F44336'; // Red - Critical
  };

  const getScoreLabel = (score) => {
    if (score <= 2) return 'Harmless';
    if (score <= 4) return 'Low Risk';
    if (score <= 6) return 'Medium';
    if (score <= 8) return 'High Risk';
    return 'Critical/Nation-State';
  };

  return (
    <div className="threat-score-viz">
      <div className="threat-score-main">
        <div
          className="threat-score-circle"
          style={{
            '--score': score,
            '--color': getScoreColor(score),
          }}
        >
          <div className="threat-score-value">{score.toFixed(1)}</div>
          <div className="threat-score-label">{getScoreLabel(score)}</div>
        </div>
      </div>

      {breakdown && (
        <div className="threat-score-breakdown">
          <h4>Score Breakdown</h4>
          {Object.entries(breakdown).map(([factor, value]) => (
            <div key={factor} className="breakdown-item">
              <span className="breakdown-label">{factor}</span>
              <div className="breakdown-bar">
                <div
                  className="breakdown-fill"
                  style={{
                    width: `${(value / 10) * 100}%`,
                    backgroundColor: getScoreColor(value),
                  }}
                />
              </div>
              <span className="breakdown-value">{value.toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}

      <style>{`
        .threat-score-viz {
          margin: 2rem 0;
          padding: 1.5rem;
          border: 1px solid var(--ifm-color-emphasis-200);
          border-radius: 8px;
          background: var(--ifm-background-surface-color);
        }
        .threat-score-main {
          display: flex;
          justify-content: center;
          margin-bottom: 2rem;
        }
        .threat-score-circle {
          width: 200px;
          height: 200px;
          border-radius: 50%;
          border: 8px solid var(--color);
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          background: var(--ifm-background-color);
        }
        .threat-score-value {
          font-size: 3rem;
          font-weight: bold;
          color: var(--color);
        }
        .threat-score-label {
          font-size: 1rem;
          color: var(--ifm-color-content-secondary);
          margin-top: 0.5rem;
        }
        .threat-score-breakdown {
          margin-top: 2rem;
        }
        .breakdown-item {
          display: flex;
          align-items: center;
          gap: 1rem;
          margin: 0.75rem 0;
        }
        .breakdown-label {
          min-width: 150px;
          font-weight: 500;
        }
        .breakdown-bar {
          flex: 1;
          height: 24px;
          background: var(--ifm-color-emphasis-100);
          border-radius: 12px;
          overflow: hidden;
        }
        .breakdown-fill {
          height: 100%;
          transition: width 0.3s ease;
        }
        .breakdown-value {
          min-width: 50px;
          text-align: right;
          font-weight: 600;
        }
      `}</style>
    </div>
  );
}
