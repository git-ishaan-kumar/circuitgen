import {copyFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';

const websiteRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = resolve(websiteRoot, '..');
const imageDirectory = resolve(websiteRoot, 'static', 'img');

await mkdir(imageDirectory, {recursive: true});

for (const name of [
  'icon-dark.svg',
  'icon-light.svg',
  'example-dark.svg',
  'example-light.svg',
]) {
  await copyFile(resolve(repositoryRoot, 'assets', name), resolve(imageDirectory, name));
}

await copyFile(resolve(repositoryRoot, 'assets', 'icon-light.svg'),
                resolve(imageDirectory, 'favicon.svg'));
