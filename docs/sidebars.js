/**
 * Creating a sidebar enables you to:
 - create an ordered group of docs
 - render a sidebar for each doc of that group
 - provide next/previous navigation

 The sidebars can be generated from the filesystem, or explicitly defined here.

 Create as many sidebars as you want.
 */

// @ts-check

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  // Main documentation sidebar
  docs: [
    {
      type: 'category',
      label: 'Getting Started',
      items: [
        'getting-started/installation',
        'getting-started/quick-start',
        'getting-started/configuration',
      ],
    },
    {
      type: 'category',
      label: 'User Guides',
      items: [
        'guides/tui-usage',
        'guides/forwarding',
        'guides/shunt-mode',
        'guides/launcher',
        'guides/web-interface',
        'guides/gui',
        'guides/api-examples',
        'guides/agents',
        'guides/quick-start-guide',
      ],
    },
    {
      type: 'category',
      label: 'Deployment',
      items: [
        'deployment/docker',
        'deployment/systemd',
      ],
    },
  ],

  // Features sidebar
  features: [
    {
      type: 'category',
      label: 'Core Features',
      items: [
        'features/advanced-features',
        'features/threat-scoring',
        'features/ai-intelligence',
      ],
    },
    {
      type: 'category',
      label: 'Advanced Capabilities',
      items: [
        'features/vector-database',
        'features/cnsa-cryptography',
        'features/temporal-analysis',
        'features/attribution-engine',
        'features/int8-acceleration',
        'features/int8-implementation-status',
      ],
    },
    {
      type: 'category',
      label: 'Planning & Roadmap',
      items: [
        'features/advanced-enhancements-plan',
        'features/next-generation-features',
      ],
    },
  ],

  // API sidebar
  api: [
    'api/cli-reference',
    'api/api-examples',
    'api/accounts',
    'api/discovery',
    'api/network',
    'api/archive',
    'api/batch',
    'api/parallel',
  ],

  // Reference sidebar
  reference: [
    {
      type: 'category',
      label: 'Technical Reference',
      items: [
        'reference/database-schema',
        'reference/database-integration',
        'reference/project-structure',
        'reference/vector-database-architecture',
        'reference/orchestration-system',
      ],
    },
    {
      type: 'category',
      label: 'Security & Compliance',
      items: [
        'reference/security-cnsa',
        'reference/third-party-licenses',
      ],
    },
    {
      type: 'category',
      label: 'Architecture & Planning',
      items: [
        'reference/feature-integration',
        'reference/production-readiness',
        'reference/strategic-roadmap',
      ],
    },
    {
      type: 'category',
      label: 'Project Information',
      items: [
        'reference/changelog',
      ],
    },
  ],
};

module.exports = sidebars;
