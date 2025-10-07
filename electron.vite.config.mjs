import { defineConfig } from 'electron-vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

const rendererRoot = resolve(__dirname, 'src/renderer');

export default defineConfig({
  main: {
    entry: resolve(__dirname, 'src/main/index.js'),
    vite: {
      build: {
	sourcemap: true,
	rollupOptions: {
          external: ['electron', 'path', 'fs', 'url', 'child_process']
        }
      }
    }
  },
  preload: {
    input: {
      index: resolve(__dirname, 'src/preload/index.js')
    },
    vite: {
      build: {
	sourcemap: true,
	rollupOptions: {
          external: ['electron', 'path', 'url']
        }
      }
    }
  },
  renderer: {
    plugins: [react()],
    server: {
      port: 5173
    },
    build: {
      sourcemap: true,
    }
  }
});
