// @ts-check
// Note: type annotations allow type checking and IDEs autocompletion

const lightCodeTheme = require('prism-react-renderer').themes.github;
const darkCodeTheme = require('prism-react-renderer').themes.dracula;

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'SPECTRA Documentation',
  tagline: 'Spectrally-Processing Extraction, Crawling, & Tele-Reconnaissance Archive',
  favicon: 'img/favicon.ico',

  // Set the production url of your site here
  url: 'https://swordintel.github.io',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For local development, use '/' for GitHub pages deployment, use '/SPECTRA/'
  baseUrl: process.env.NODE_ENV === 'production' ? '/SPECTRA/' : '/',

  // GitHub pages deployment config.
  organizationName: 'SWORDIntel',
  projectName: 'SPECTRA',
  deploymentBranch: 'gh-pages',
  trailingSlash: false,

  onBrokenLinks: 'warn',
  onBrokenMarkdownLinks: 'warn',

  // Even if you don't use internalization, you can use this field to set useful
  // metadata like html lang. For example, if your site is Chinese, you may want
  // to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  clientModules: [require.resolve('./src/clientModules.js')],
  
  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: require.resolve('./sidebars.js'),
          editUrl: 'https://github.com/SWORDIntel/SPECTRA/tree/main/docs/',
          showLastUpdateAuthor: true,
          showLastUpdateTime: true,
        },
        blog: {
          showReadingTime: true,
          editUrl: 'https://github.com/SWORDIntel/SPECTRA/tree/main/docs/',
        },
        theme: {
          customCss: require.resolve('./src/css/custom.css'),
        },
      }),
    ],
  ],

  themes: ['@docusaurus/theme-mermaid'],

  markdown: {
    mermaid: true,
  },

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      // Replace with your project's social card
      image: 'img/SPECTRA.png',
      navbar: {
        title: 'SPECTRA',
        logo: {
          alt: 'SPECTRA Logo',
          src: 'img/SPECTRA.png',
          srcDark: 'img/SPECTRA.png',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docs',
            position: 'left',
            label: 'Docs',
          },
          {
            type: 'docSidebar',
            sidebarId: 'features',
            position: 'left',
            label: 'Features',
          },
          {
            type: 'docSidebar',
            sidebarId: 'api',
            position: 'left',
            label: 'API',
          },
          {
            type: 'docSidebar',
            sidebarId: 'reference',
            position: 'left',
            label: 'Reference',
          },
          {
            href: 'https://github.com/SWORDIntel/SPECTRA',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Documentation',
            items: [
              {
                label: 'Getting Started',
                to: '/docs/getting-started/installation',
              },
              {
                label: 'User Guides',
                to: '/docs/guides/tui-usage',
              },
              {
                label: 'API Reference',
                to: '/docs/api/cli-reference',
              },
            ],
          },
          {
            title: 'Features',
            items: [
              {
                label: 'Advanced Features',
                to: '/docs/features/advanced-features',
              },
              {
                label: 'Threat Scoring',
                to: '/docs/features/threat-scoring',
              },
              {
                label: 'AI Intelligence',
                to: '/docs/features/ai-intelligence',
              },
            ],
          },
          {
            title: 'Resources',
            items: [
              {
                label: 'GitHub',
                href: 'https://github.com/SWORDIntel/SPECTRA',
              },
              {
                label: 'Issues',
                href: 'https://github.com/SWORDIntel/SPECTRA/issues',
              },
            ],
          },
        ],
        copyright: `Copyright © ${new Date().getFullYear()} SWORDIntel. Built with Docusaurus.`,
      },
      prism: {
        theme: lightCodeTheme,
        darkTheme: darkCodeTheme,
        additionalLanguages: ['bash', 'python', 'json', 'yaml', 'toml'],
      },
      colorMode: {
        defaultMode: 'dark',
        disableSwitch: false,
        respectPrefersColorScheme: false, // Force dark mode, ignore system preference
      },
      // Algolia search disabled - can be enabled later with proper credentials
      // algolia: {
      //   appId: 'YOUR_APP_ID',
      //   apiKey: 'YOUR_SEARCH_API_KEY',
      //   indexName: 'spectra',
      //   contextualSearch: true,
      // },
    }),
};

module.exports = config;
