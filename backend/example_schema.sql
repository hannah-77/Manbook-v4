-- Contoh skema SQL untuk proyek berbasis PostgreSQL dengan struktur umum alat kesehatan

CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    product_code VARCHAR(20) UNIQUE NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    description TEXT,
    specifications JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chapters (
    chapter_id SERIAL PRIMARY KEY,
    chapter_number VARCHAR(10) NOT NULL UNIQUE,
    title_en VARCHAR(100) NOT NULL,
    title_id VARCHAR(100) NOT NULL
);

CREATE TABLE manual_content (
    content_id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(product_id),
    chapter_id INTEGER REFERENCES chapters(chapter_id),
    sequence_number INTEGER NOT NULL,
    content_type VARCHAR(20) CHECK(content_type IN ('heading', 'paragraph', 'warning', 'figure', 'table')),
    content_text TEXT,
    image_path VARCHAR(255),
    lang VARCHAR(2) DEFAULT 'id',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Insert data contoh
INSERT INTO chapters (chapter_number, title_en, title_id) VALUES
('Chapter 1', 'Intended Use & Safety', 'Tujuan Penggunaan & Keamanan'),
('Chapter 2', 'Installation', 'Instalasi');

-- Index untuk performa
CREATE INDEX idx_manual_content_product ON manual_content(product_id);
CREATE INDEX idx_manual_content_chapter ON manual_content(chapter_id);