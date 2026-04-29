# Gambar 5.1: Diagram Arsitektur Sistem (Manbook-v4)

Diagram di bawah ini menggambarkan arsitektur *Client-Server* dari aplikasi Manbook-v4. Frontend dibangun dengan Flutter, sedangkan Backend menggunakan FastAPI dengan pipeline Computer Vision dan Generative AI.

```mermaid
graph TD
    %% Styling
    classDef frontend fill:#02569B,stroke:#fff,stroke-width:2px,color:#fff;
    classDef backend fill:#009688,stroke:#fff,stroke-width:2px,color:#fff;
    classDef vision fill:#FF9800,stroke:#fff,stroke-width:2px,color:#fff;
    classDef ai fill:#673AB7,stroke:#fff,stroke-width:2px,color:#fff;
    classDef storage fill:#607D8B,stroke:#fff,stroke-width:2px,color:#fff;

    subgraph "Frontend Layer (Flutter Desktop)"
        UI[User Interface]:::frontend
        Editor[Report Editor & Preview]:::frontend
        StateMgr[State Management & API Client]:::frontend
        
        UI --> Editor
        UI --> StateMgr
    end

    subgraph "Backend Layer (FastAPI / Python)"
        API[FastAPI Endpoints]:::backend
        
        subgraph "Vision Engine Pipeline"
            Prep[Image Preprocessing\nOpenCV, Deskew, CLAHE]:::vision
            Layout[Layout Detection\nSurya ML]:::vision
            OCR[Text Extraction\nPaddleOCR & Tesseract]:::vision
            
            Prep --> Layout --> OCR
        end

        subgraph "AI & NLP Pipeline"
            Orchestrator[AI Orchestrator\norchestrator.py]:::ai
            LLM[OpenRouter Client\nGemini 2.0]:::ai
            
            Orchestrator <--> LLM
        end

        subgraph "Report Generation"
            BioArch[BioArchitect\nDOCX Builder]:::backend
            Win32[Win32Com\nPDF Converter]:::backend
            
            BioArch --> Win32
        end

        API <--> Prep
        OCR --> Orchestrator
        Orchestrator --> BioArch
    end

    %% External Connections
    StateMgr <==>|REST API / JSON| API
    LLM -.->|API Call| ExternalAPI((External LLM APIs)):::storage
    Win32 --> LocalStorage[(Local File System\nGenerated Reports)]:::storage

```

---

# Gambar 5.2: Alur Kerja Sistem (System Workflow)

Alur kerja di bawah menunjukkan proses *end-to-end* sejak pengguna mengunggah dokumen hingga dokumen hasil normalisasi berhasil diunduh.

```mermaid
sequenceDiagram
    participant User
    participant Frontend as Flutter App
    participant API as FastAPI Backend
    participant Vision as Vision Engine (OCR)
    participant AI as AI Orchestrator
    participant Builder as Report Builder

    User->>Frontend: Upload Dokumen (PDF/DOCX/JPG)
    Frontend->>API: POST /detect-language & /start
    
    API->>Vision: Preprocessing (Split Column, Auto-Upscale)
    Vision-->>API: Clean Images Ready
    
    Frontend->>API: POST /process (Upload file & Polling)
    
    rect rgb(240, 248, 255)
        Note right of API: Tahap Ekstraksi & Analisis Visual
        API->>Vision: _scan_document()
        Vision->>Vision: Deteksi Layout (Surya) & Filter Visual
        Vision->>Vision: Pre-OCR Inversion (Untuk Teks Latar Hitam)
        Vision->>Vision: Ekstraksi Teks (PaddleOCR / Tesseract)
        Vision-->>API: Raw Text Elements & Bounding Boxes
    end
    
    rect rgb(245, 240, 255)
        Note right of API: Tahap Normalisasi & Klasifikasi AI
        API->>AI: analyze_chunk_with_ai()
        AI->>AI: Ekstraksi Metadata & Klasifikasi BAB (1-7)
        AI->>AI: Terjemahan Bahasa (Opsional)
        AI-->>API: Structured JSON Data
    end
    
    rect rgb(240, 255, 240)
        Note right of API: Tahap Pembuatan Laporan Akhir
        API->>Builder: build_report(structured_data)
        Builder->>Builder: Susun DOCX (Cover, Tabel, Gambar, Format)
        Builder->>Builder: Konversi DOCX ke PDF (Win32com - Silent)
        Builder-->>API: URLs (Word & PDF)
    end
    
    API-->>Frontend: Response (Success, Structured Data, URLs)
    
    Frontend->>User: Tampilkan 'Preview & Edit' (Cover, Chapters)
    User->>Frontend: Koreksi Teks & Modifikasi Struktur
    Frontend->>API: POST /generate_custom_report
    API->>Builder: Update Dokumen
    Builder-->>Frontend: Return Updated URLs
    Frontend->>User: Download Dokumen Normalisasi (Word/PDF)
```
