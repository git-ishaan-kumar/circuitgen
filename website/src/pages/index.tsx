import {useState, type ReactNode} from 'react';
import CodeBlock from '@theme/CodeBlock';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';
import useBaseUrl from '@docusaurus/useBaseUrl';
import styles from './index.module.css';

const installCommand = 'pip install circuitgen';
const example = `from circuitgen import generate

generate(
    "A 9 V battery connected in series with a "
    "360 Ω resistor and a red LED.",
    provider="gemini",
    model="gemini-3.5-flash-lite",
    output="circuit.svg"
)`;

const features = [
  {
    title: 'Generate',
    text: 'Create schematics from text descriptions with your preferred AI provider.',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 3.75h7l4 4v12.5H7z"/><path d="M14 3.75v4h4M10 13h5M10 16h5"/><path d="m5 7-1.5 1.5L5 10"/></svg>,
  },
  {
    title: 'Render',
    text: 'Automatically place components and route wires from netlists, entirely offline.',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="5" cy="6" r="2"/><circle cx="19" cy="18" r="2"/><path d="M7 6h4a3 3 0 0 1 3 3v2a3 3 0 0 0 3 3h2M5 8v8"/><circle cx="5" cy="18" r="2"/></svg>,
  },
  {
    title: 'Integrate',
    text: 'Use Python or the CLI and export to SVG, PNG, or PDF.',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m8.5 7-5 5 5 5M15.5 7l5 5-5 5M14 5l-4 14"/></svg>,
  },
];

export default function Home(): ReactNode {
  const [copied, setCopied] = useState(false);
  const logo = useBaseUrl('/img/icon-dark.svg');
  const darkSchematic = useBaseUrl('/img/example-dark.svg');
  const lightSchematic = useBaseUrl('/img/example-light.svg');

  async function copyInstallCommand() {
    try {
      await navigator.clipboard.writeText(installCommand);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Layout
      title="Circuit schematics from text or netlists"
      description="CircuitGen is a Python library and CLI for generating circuit schematics from text descriptions or netlists.">
      <main className={styles.main}>
        <section className={styles.hero}>
          <div className={styles.brand}>
            <img className={styles.logo} src={logo} alt="" aria-hidden="true" />
            <h1>CircuitGen</h1>
          </div>
          <p className={styles.tagline}>Generate circuit schematics from text descriptions or netlists.</p>
          <div className={styles.actions}>
            <Link className="button button--primary button--lg" to="/docs/getting-started">Get Started</Link>
            <Link className="button button--secondary button--lg" to="/api">API Reference</Link>
            <Link className="button button--secondary button--lg" to="/help">Help</Link>
          </div>
          <div className={styles.install}>
            <code>{installCommand}</code>
            <button type="button" onClick={copyInstallCommand} aria-label={copied ? 'Install command copied' : 'Copy install command'} title={copied ? 'Copied' : 'Copy'}>
              {copied ? (
                <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3.2 3.2L13 4.5" /></svg>
              ) : (
                <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="5" width="8" height="9" rx="1" /><path d="M10.5 3H4a1 1 0 0 0-1 1v8" /></svg>
              )}
            </button>
            <span className={styles.copyStatus} aria-live="polite">{copied ? 'Command copied' : ''}</span>
          </div>
        </section>

        <section className={styles.features} aria-label="What CircuitGen does">
          {features.map((feature) => (
            <article className={styles.feature} key={feature.title}>
              <span className={styles.featureIcon}>{feature.icon}</span>
              <h2>{feature.title}</h2>
              <p>{feature.text}</p>
            </article>
          ))}
        </section>

        <section className={styles.example}>
          <div>
            <h2>Example</h2>
            <CodeBlock language="python">{example}</CodeBlock>
          </div>
          <figure className={styles.schematic}>
            <img className={styles.darkSchematic} src={darkSchematic} alt="Battery, 360 ohm resistor, and red LED in a closed circuit" />
            <img className={styles.lightSchematic} src={lightSchematic} alt="" aria-hidden="true" />
          </figure>
        </section>
      </main>
    </Layout>
  );
}
