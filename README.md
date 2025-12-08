# job-intelligence-engine
# Job Intelligence Engine (JIE)

# Job Intelligence Engine (JIE)

An AI-powered job intelligence system that monitors frontier AI company careers pages, classifies roles, matches them to a candidate profile, and generates insights and alerts.

## Status

Early development. Architecture and project plan in progress.

## Goals

- Continuously scrape OpenAI careers (later: Anthropic, Google, etc.)
- Classify roles by function (Solutions Architecture, AI Deployment, CS, etc.)
- Compute a fit score and gap analysis against a structured candidate profile
- Generate weekly hiring trend summaries and real-time alerts for high-fit roles
- Demonstrate practical use of LLMs, embeddings, and workflow automation

## Architecture

High level:

- Provider-agnostic scraper layer  
- Embedding + classification pipeline (OpenAI API)  
- Matching engine (fit + gaps)  
- Insight generator (weekly / monthly pulse)  
- Notification & dashboard layer  

```mermaid
flowchart TD

    subgraph Source[Job Source Ecosystem]
        OA[OpenAI Careers]
        AN[Anthropic Careers]
        GM[Google DeepMind Careers]
        MT[Meta Careers]
    end

    subgraph Scraper[1. Provider-Agnostic Scraper Layer]
        SCR[Scraper Manager]
        OA --> SCR
        AN --> SCR
        GM --> SCR
        MT --> SCR
    end

    SCR --> RAW[(Raw Job Data Store)]

    subgraph Embed[2. Embedding & Preprocessing Pipeline]
        CLEAN[HTML Cleaning & Text Normalization]
        EMBED[OpenAI Embeddings API]
        VEC[(Vector Store: FAISS / DynamoDB)]
    end

    RAW --> CLEAN --> EMBED --> VEC

    subgraph Classifier[3. Classification Engine]
        CLASS[LLM Role Classifier]
        META[Structured Metadata Extractor]
    end

    VEC --> CLASS --> META

    subgraph Match[4. Matching Engine]
        PROFILE[Candidate Skill Profile JSON]
        MATCH[Fit Score + Gap Analysis Engine]
    end

    META --> MATCH
    PROFILE --> MATCH

    subgraph Insights[5. Insight & Trend Engine]
        WEEKLY[Weekly Hiring Pulse Generator]
        MONTHLY[Trend Analyzer]
        PREDICT[LLM-Based Hiring Forecast]
    end

    MATCH --> WEEKLY
    MATCH --> MONTHLY
    META --> PREDICT

    subgraph Notify[6. Notification & Dashboard Layer]
        DISCORD[Discord Alerts]
        NLM[Notebook Feed]
        EMAIL[Email Summary]
        DASH[Streamlit Dashboard]
    end

    WEEKLY --> DISCORD
    WEEKLY --> NLM
    WEEKLY --> EMAIL

    MONTHLY --> DASH
    MATCH --> DASH

AI-Assisted Development

This project is intentionally built using AI pair programming:

GPT-5 is used for design, code generation, and refactoring.

A second model (e.g. Gemini) is used as a cross-model reviewer for critical modules (scraper, matching engine, etc.).

The goal is to demonstrate practical, safe use of multi-model workflows for software engineering.

Roadmap

Sprint 0: Repo setup, models, and basic scraper skeleton

Sprint 1: Raw scraping of OpenAI careers → JSON

Sprint 2: Embeddings + basic classification

Sprint 3: Matching engine + Discord alerts

Sprint 4: Insights + Streamlit dashboard

Sprint 5: Add additional providers (Anthropic, etc.)