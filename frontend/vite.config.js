import {defineConfig} from 'vite';

export default defineConfig({
    // Під час розробки проксі буде направляти /api на backend:8000
    server: {
        proxy: {
            '/api': 'http://localhost:8000',
            '/media': 'http://localhost:8000',
        }
    },
    // Для production збірки
    build: {
        outDir: 'dist',
    },
    base: './',
});