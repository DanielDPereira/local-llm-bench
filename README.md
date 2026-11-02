# Local LLM Bench

**Sugestão de repositório:** `local-llm-bench`  
**Descrição curta:** Dashboard local para comparar modelos Ollama por TTFT, tokens/s, tempo total, CPU, RAM e GPU.

Aplicação simples para executar o mesmo prompt em diferentes modelos locais e comparar velocidade e consumo aproximado de hardware. Backend em FastAPI + Ollama; frontend em HTML/CSS/JavaScript com Chart.js.

## O que mede

| Métrica | Significado |
|---|---|
| TTFT (s) | Tempo até o primeiro fragmento de resposta chegar ao cliente. |
| Geração (tokens/s) | Throughput informado pelo Ollama: tokens gerados / duração de geração. |
| Tokens/s de parede | Tokens gerados / tempo total observado pelo benchmark. Disponível no retorno da API. |
| Tempo total (s) | Duração completa da chamada, incluindo carregamento, prompt e geração. |
| Prompt tokens/s | Throughput de processamento do prompt/contexto, informado pelo Ollama. |
| Load time (s) | Tempo de carregamento do modelo informado pelo Ollama. |
| CPU (%) | Pico das amostras de utilização total da CPU durante a execução. |
| RAM (MB) | Pico de memória usada pelo sistema durante a execução; não é RAM exclusiva do modelo. |
| GPU (%) / VRAM | Utilização e memória da primeira GPU NVIDIA, quando NVML estiver disponível. |
| Tokens de saída | Quantidade de tokens gerados reportada pelo Ollama. |

**Interpretação:** TTFT menor é melhor para interatividade; tokens/s maior é melhor para geração; tempo total menor é melhor para tarefas equivalentes. Não compare execuções com prompts, limites de saída ou configurações diferentes.

## Requisitos

- Python 3.10 ou superior.
- [Ollama](https://ollama.com/) instalado e em execução.
- Pelo menos um modelo baixado no Ollama.
- Navegador moderno.
- GPU NVIDIA é opcional. Sem NVIDIA, o app continua funcionando e exibe GPU como indisponível.

## Instalação rápida

### 1. Baixe um modelo no Ollama

Exemplo:

```bash
ollama pull qwen2.5:1.5b
ollama pull gemma3:1b
ollama list
```

Use modelos compatíveis com a memória disponível na máquina. Os nomes acima são exemplos; o app detecta automaticamente o que estiver instalado.

### 2. Clone e prepare o ambiente

```bash
git clone https://github.com/SEU-USUARIO/local-llm-bench.git
cd local-llm-bench

python -m venv .venv
```

Ative o ambiente:

**Windows PowerShell**
```powershell
.venv\Scripts\Activate.ps1
```

**Linux / macOS / WSL**
```bash
source .venv/bin/activate
```

Instale as dependências:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Inicie o servidor

Confirme que o Ollama está acessível em `http://localhost:11434`.

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Abra **http://127.0.0.1:8000**.

A documentação interativa da API fica em **http://127.0.0.1:8000/docs**.

## Configuração

Por padrão, o backend usa `http://localhost:11434`. Para apontar para outra instância:

**PowerShell**
```powershell
$env:OLLAMA_URL="http://localhost:11434"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Linux / macOS / WSL**
```bash
OLLAMA_URL=http://localhost:11434 uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Se o backend estiver no WSL e o Ollama no Windows, `localhost` pode ou não funcionar dependendo da configuração de rede do WSL. Nesse caso, configure `OLLAMA_URL` com o endereço do host Windows acessível a partir do WSL. Não exponha o servidor de benchmark à rede pública.

## Como usar

1. Inicie o Ollama e confirme que os modelos aparecem em `ollama list`.
2. Abra o dashboard e clique em **Atualizar modelos**.
3. Escolha o modelo e mantenha o mesmo prompt para todos os modelos.
4. Configure o número de execuções (1, 2, 3 ou 5), o limite de tokens e a temperatura.
5. Clique em **Executar benchmark**.
6. Observe os indicadores, a tabela comparativa e os gráficos.
7. Selecione outro modelo e repita sem alterar o prompt/configurações.
8. Exporte a tabela da sessão em CSV, se desejar.

Cada execução usa uma chamada de geração não-streaming? **Não**: o backend consome o stream do Ollama para estimar TTFT. As execuções são sequenciais, evitando concorrência entre modelos.

## Recomendações para testes justos

- **Mesmo prompt:** use exatamente o mesmo texto para todos os modelos.
- **Mesmo limite de saída:** mantenha `num_predict` igual.
- **Aquecimento:** a primeira execução pode carregar pesos para a RAM/VRAM. Rode uma execução de aquecimento e depois compare as seguintes.
- **Ordem:** alterne a ordem dos modelos em novos ciclos para reduzir viés térmico/cache.
- **Energia:** use o mesmo perfil de energia e mantenha o notebook conectado à tomada.
- **Repetição:** prefira 3 a 5 execuções e compare médias; observe também dispersão e valores individuais na resposta da API.
- **Contexto:** prompts maiores aumentam o processamento de entrada e podem afetar TTFT.
- **Quantização:** registre a tag/quantização do modelo; modelos com quantizações diferentes não são comparação equivalente.
- **Temperatura:** use temperatura baixa para reduzir variação, embora não garanta respostas idênticas.

## API

- `GET /api/health` — verifica conexão com Ollama.
- `GET /api/models` — lista modelos locais, tamanho, família, parâmetros e quantização.
- `GET /api/system` — informações do ambiente e snapshot de hardware.
- `POST /api/benchmark` — executa o benchmark.

Exemplo de requisição:

```json
{
  "model": "qwen2.5:1.5b",
  "prompt": "Explique o que é RAG em até 100 palavras.",
  "runs": 3,
  "temperature": 0.2,
  "num_predict": 256
}
```

O endpoint retorna cada execução, médias e amostras de hardware. Campos de maior interesse: `ttft_s`, `generation_tokens_per_second`, `wall_tokens_per_second`, `prompt_tokens_per_second`, `total_time_s`, `load_time_s`, `hardware_peak`.

## Métricas de hardware: limitações

- CPU e RAM são métricas globais do sistema obtidas por amostragem a cada ~0,5 s. Não representam consumo exclusivo do processo Ollama.
- A amostragem pode perder picos curtos.
- GPU/VRAM é implementada para NVIDIA via NVML. Para habilitar, instale `pip install nvidia-ml-py` em ambiente com driver NVIDIA funcional. Em GPU AMD/Intel ou ambiente sem NVML, a métrica fica indisponível.
- Em máquinas com mais de uma GPU, a versão inicial consulta apenas a GPU de índice zero.
- No Windows + WSL, as métricas de CPU/RAM refletem o ambiente onde o backend está rodando. A disponibilidade da GPU depende do suporte do driver/ambiente.

## Estrutura

```text
local-llm-bench/
├── app/
│   ├── __init__.py
│   ├── main.py
│   └── static/
│       └── index.html
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Solução de problemas

**Ollama indisponível**
- Abra o aplicativo Ollama ou execute `ollama serve`.
- Teste `http://localhost:11434/api/version`.
- Confira `OLLAMA_URL`.

**Nenhum modelo aparece**
- Execute `ollama pull nome-do-modelo`.
- Confira com `ollama list` e clique em Atualizar modelos.

**Erro de modelo não encontrado**
- Use o nome completo exibido pelo `ollama list`, incluindo a tag, por exemplo `qwen2.5:1.5b`.

**Benchmark lento**
- A primeira chamada pode incluir carregamento do modelo.
- Diminua `num_predict` ou use um modelo menor.
- Evite executar outros workloads simultaneamente.

**GPU não aparece**
- O suporte automático desta versão é NVIDIA/NVML. Instale `nvidia-ml-py` e valide o driver com `nvidia-smi`.

## Segurança e escopo

O dashboard foi pensado para uso local e não implementa autenticação. O servidor padrão escuta apenas em `127.0.0.1`; mantenha assim em uso pessoal. Não publique a porta na internet. O prompt é enviado apenas à instância Ollama configurada.

## Próximas evoluções possíveis

- Persistência de benchmarks em SQLite.
- Mediana, desvio-padrão e percentis de TTFT/tokens/s.
- Métricas por processo (RSS do Ollama) e suporte AMD/Intel.
- Comparação de qualidade com conjunto fixo de perguntas e avaliação humana.
- Exportação JSON e relatórios HTML.
- Benchmark de concorrência e tamanhos de contexto.
