import {themes as prismThemes} from 'prism-react-renderer';
import type {PrismTheme} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const githubDark: PrismTheme = {
  plain: {color: '#e6edf3', backgroundColor: '#0d1117'},
  styles: [
    {types: ['comment', 'prolog', 'doctype', 'cdata'], style: {color: '#8b949e', fontStyle: 'italic'}},
    {types: ['namespace'], style: {opacity: 0.7}},
    {types: ['string', 'attr-value', 'char', 'inserted'], style: {color: '#a5d6ff'}},
    {types: ['punctuation', 'operator'], style: {color: '#e6edf3'}},
    {types: ['entity', 'url', 'symbol', 'number', 'boolean', 'variable', 'constant', 'property', 'regex'], style: {color: '#79c0ff'}},
    {types: ['atrule', 'keyword', 'attr-name', 'selector'], style: {color: '#ff7b72'}},
    {types: ['function', 'function-variable', 'class-name'], style: {color: '#d2a8ff'}},
    {types: ['tag', 'deleted'], style: {color: '#ffa198'}},
  ],
};

const config: Config = {
  title: 'CircuitGen',
  tagline: 'Generate circuit schematics from text descriptions or netlists.',
  favicon: 'img/favicon.svg',
  url: 'https://git-ishaan-kumar.github.io',
  baseUrl: '/circuitgen/',
  organizationName: 'git-ishaan-kumar',
  projectName: 'circuitgen',
  trailingSlash: false,
  onBrokenLinks: 'throw',
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },
  presets: [
    [
      'classic',
      {
        docs: {
          routeBasePath: 'docs',
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/git-ishaan-kumar/circuitgen/edit/main/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],
  themes: [
    [
      require.resolve('@easyops-cn/docusaurus-search-local'),
      {
        hashed: 'filename',
        indexDocs: true,
        indexBlog: false,
        indexPages: true,
        language: ['en'],
        removeDefaultStopWordFilter: true,
        searchBarPosition: 'right',
      },
    ],
  ],
  themeConfig: {
    metadata: [
      {name: 'keywords', content: 'CircuitGen, circuits, schematics, Python'},
    ],
    colorMode: {
      defaultMode: 'dark',
      respectPrefersColorScheme: false,
    },
    navbar: {
      title: 'CircuitGen',
      logo: {
        alt: 'CircuitGen',
        src: 'img/icon-dark.svg',
      },
      items: [
        {to: '/docs/getting-started', label: 'Docs', position: 'right'},
        {to: '/api', label: 'API', position: 'right'},
        {to: '/help', label: 'Help', position: 'right'},
        {
          type: 'html',
          position: 'right',
          value: '<a class="navbar__link circuitgen-github" href="https://github.com/git-ishaan-kumar/circuitgen" aria-label="CircuitGen on GitHub" title="GitHub"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.387-1.333-1.757-1.333-1.757-1.09-.745.083-.73.083-.73 1.205.084 1.84 1.238 1.84 1.238 1.07 1.835 2.807 1.305 3.492.998.108-.776.42-1.305.763-1.605-2.665-.3-5.467-1.334-5.467-5.931 0-1.31.468-2.381 1.235-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.323 3.3 1.23a11.5 11.5 0 0 1 3.003-.404c1.02.005 2.047.138 3.003.404 2.29-1.553 3.296-1.23 3.296-1.23.655 1.652.244 2.873.12 3.176.77.84 1.233 1.911 1.233 3.221 0 4.61-2.807 5.628-5.48 5.921.43.372.814 1.102.814 2.222 0 1.604-.015 2.896-.015 3.286 0 .322.216.694.825.576C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg></a>',
        },
      ],
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: githubDark,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
