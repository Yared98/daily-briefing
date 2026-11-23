# Daily Briefing Executivo

Pipeline modular em Python que coleta métricas de trabalho, repositórios, segurança, notícias/IA, finanças e saúde de infraestrutura, consolidando tudo em um relatório diário publicado no Google Docs (ou Markdown local) com um prompt pronto para assistentes matinais (Gemini / Claude).

## Arquitetura

```text
collectors/ (feature flags em config.yaml)
   ├── businessmap.py      -> Kanbanize / Businessmap API v2
   ├── github_trending.py  -> Repositórios em alta (GitHub API)
   ├── news_ai.py          -> Manchetes & IA (Tavily API)
   ├── repo_security.py    -> Git status + Dependabot / OSV.dev
   ├── infra_health.py     -> Disco, RAM, CPU e Docker local
   └── homelab_db.py       -> Kanbn, Securo e Umami via PostgreSQL (opcional)
        │
        ▼
formatters/briefing.py     -> Consolida Markdown + Prompt (templates/assistant_prompt.md)
        │
        ▼
publishers/
   ├── google_docs.py      -> Atualiza documento fixo via Service Account
   └── local_markdown.py   -> Grava em output/daily_briefing.md (--dry-run)
```

## Setup Rápido

Requer **Python 3.11+** (Linux, macOS ou Windows).

1. **Instalar dependências:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configurar variáveis e módulos:**
   ```bash
   cp .env.example .env
   cp config.example.yaml config.yaml
   ```
   Edite `.env` com suas chaves e habilite em `config.yaml` apenas os coletores que deseja usar.

3. **Testar localmente (sem Google Cloud):**
   ```bash
   python main.py --dry-run
   ```

## Configurar Google Docs (Service Account)

1. No Google Cloud Console, crie um projeto e ative **Google Docs API** e **Google Drive API**.
2. Crie uma **Service Account** e gere uma chave JSON salvando como `service_account.json` na raiz do projeto.
3. Crie um Google Doc em branco (ex: *"Daily Briefing - Atual"*), copie o ID da URL (`/d/<DOC_ID>/edit`) para `GOOGLE_DOC_ID` no `.env`.
4. Compartilhe esse documento com o `client_email` da Service Account dando permissão de **Editor**.
5. Altere `publisher.mode` para `"google_docs"` no `config.yaml` e execute `python main.py`.

## Personalização

- **Prompt do assistente:** edite `templates/assistant_prompt.md` (ou aponte `assistant_prompt.template_path` para outro arquivo). Variáveis disponíveis: `$owner_name`, `$briefing_ref`, `$doc_name`, `$agenda_hint` e `$focus_items` (lista montada a partir dos coletores habilitados). Desligue com `assistant_prompt.enabled: false`.
- **Tabela de referência de modelos:** `collectors.news_ai.model_reference` é uma lista mantida à mão (nome, preço, observação). Vem desligada; não há busca automática de preços.
- **Segurança de dependências:** em `supported_projects`, o campo `pkg` aceita `package.json` (npm), `requirements*.txt` ou `pyproject.toml` (PyPI, PEP 621 e Poetry). Sem `GITHUB_TOKEN` (ou sem acesso ao Dependabot do repositório), as versões são consultadas no [OSV.dev](https://osv.dev). Para faixas como `>=1.2` ou `^1.2`, é usada a versão mínima, o que pode apontar alertas já resolvidos na versão instalada.
- **Infraestrutura:** disco funciona em qualquer sistema; RAM e load average só em Linux; Docker quando o comando `docker` estiver disponível.

## Agendamento

**Linux / macOS (cron):**

```cron
0 8 * * * cd /opt/daily-briefing && /opt/daily-briefing/.venv/bin/python main.py >> /var/log/daily_briefing.log 2>&1
```

**Windows (Agendador de Tarefas):**

```powershell
schtasks /Create /SC DAILY /ST 08:00 /TN "Daily Briefing" /TR "cmd /c cd /d C:\caminho\daily-briefing && .venv\Scripts\python.exe main.py >> daily_briefing.log 2>&1"
```
