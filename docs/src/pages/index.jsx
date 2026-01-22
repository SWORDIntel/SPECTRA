import React, {useEffect} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Logo from '@site/src/components/Logo';
import {useColorMode} from '@docusaurus/theme-common';
import styles from './index.module.css';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero hero--primary', styles.heroBanner)}>
      <div className="container">
        <div className={styles.heroContent}>
          <Logo size="large" />
          <h1 className="hero__title">{siteConfig.title}</h1>
          <p className="hero__subtitle">{siteConfig.tagline}</p>
          <div className={styles.buttons}>
            <Link
              className="button button--secondary button--lg"
              to="/docs/getting-started/installation">
              Get Started
            </Link>
            <Link
              className="button button--secondary button--lg"
              to="/docs/getting-started/quick-start">
              Quick Start
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}

function Feature({title, description, icon}) {
  return (
    <div className={clsx('col col--4', styles.feature)}>
      <div className="text--center">
        <div className={styles.featureIcon}>{icon}</div>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </div>
  );
}

function HomepageFeatures() {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          <Feature
            title="Multi-Account Support"
            description="Smart account rotation with persistent selection and failure detection for reliable operations."
            icon="🔄"
          />
          <Feature
            title="Network Discovery"
            description="Discover connected groups and channels with SQL audit trail and graph-based analysis."
            icon="🔎"
          />
          <Feature
            title="Forensic Archiving"
            description="Complete message and media archiving with integrity checksums and sidecar metadata."
            icon="📁"
          />
          <Feature
            title="Advanced Intelligence"
            description="AI/ML threat scoring, vector databases, and temporal analysis for comprehensive intelligence."
            icon="🤖"
          />
          <Feature
            title="Parallel Processing"
            description="Leverage multiple accounts and proxies simultaneously with full SQL-backed state."
            icon="⚡"
          />
          <Feature
            title="OPSEC Features"
            description="Account/proxy rotation, SQL audit trail, and robust anti-detection capabilities."
            icon="🛡️"
          />
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const {siteConfig} = useDocusaurusContext();
  const {setColorMode} = useColorMode();
  
  // Force dark theme on page load
  useEffect(() => {
    setColorMode('dark');
    // Also set it on the document element
    document.documentElement.setAttribute('data-theme', 'dark');
    // Remove light theme class if present
    document.documentElement.classList.remove('light-theme');
    document.documentElement.classList.add('dark-theme');
  }, [setColorMode]);
  
  return (
    <Layout
      title={`${siteConfig.title}`}
      description="Spectrally-Processing Extraction, Crawling, & Tele-Reconnaissance Archive - Advanced Telegram intelligence framework">
      <HomepageHeader />
      <main>
        <HomepageFeatures />
        <section className={styles.quickLinks}>
          <div className="container">
            <h2>Quick Links</h2>
            <div className="row">
              <div className="col col--4">
                <h3>Getting Started</h3>
                <ul>
                  <li><Link to="/docs/getting-started/installation">Installation Guide</Link></li>
                  <li><Link to="/docs/getting-started/quick-start">Quick Start</Link></li>
                  <li><Link to="/docs/getting-started/configuration">Configuration</Link></li>
                </ul>
              </div>
              <div className="col col--4">
                <h3>User Guides</h3>
                <ul>
                  <li><Link to="/docs/guides/tui-usage">TUI Usage</Link></li>
                  <li><Link to="/docs/guides/forwarding">Forwarding Guide</Link></li>
                  <li><Link to="/docs/api/cli-reference">CLI Reference</Link></li>
                </ul>
              </div>
              <div className="col col--4">
                <h3>Features</h3>
                <ul>
                  <li><Link to="/docs/features/advanced-features">Advanced Features</Link></li>
                  <li><Link to="/docs/features/threat-scoring">Threat Scoring</Link></li>
                  <li><Link to="/docs/features/ai-intelligence">AI Intelligence</Link></li>
                </ul>
              </div>
            </div>
          </div>
        </section>
      </main>
    </Layout>
  );
}
