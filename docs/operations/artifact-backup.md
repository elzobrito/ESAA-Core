---
titulo: "Backup e restauração de artifacts de efeitos"
tipo: "Manual técnico"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# Backup e restauração de artifacts de efeitos

**Sumário:** Escopo · Preparação · Ferramenta · Backup · Restauração e conferência · Perda definitiva · Evidência · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Procedimento executado em laboratório descartável, AUD-O2-090. |

## 1. Escopo e localização

Artifacts preservam os bytes e metadados dos efeitos finais registrados por `orchestrator.file.write`. A árvore é `.roadmap/artifacts/`: JSONs em `file-effects/` e blobs binários em `file-effects/blobs/`. A gravação e validação estão em [src/esaa/file_effects.py:347 — `write_artifact`](../../src/esaa/file_effects.py#L347) e [src/esaa/file_effects.py:389 — `verify_artifact`](../../src/esaa/file_effects.py#L389); copiar apenas os JSONs perde os bytes binários.

[gitignore-esaa](../../.gitignore) ignora essa árvore para evitar versionar cópias completas de cada efeito. Um clone do Git não carrega os artifacts. `effects recover` valida o artifact antes do destino e pode retornar `ARTIFACT_MISSING` mesmo se o arquivo final estiver no clone ([src/esaa/file_effects.py:460 — `recover_file_effects`](../../src/esaa/file_effects.py#L460)). Reprojetar tarefas não recupera esses bytes. A escolha arquitetural está em [adr-0004](../adr/0004-artifacts-fora-git.md).

## 2. Preparação e frequência

Execute como operador, com Python 3.11 ou posterior. Os comandos abaixo usam Bash; o programa de backup usa somente a biblioteca padrão do Python. O ensaio ocorreu em Linux/Python 3.11; não há validação operacional em Windows nesta entrega.

Interrompa os escritores do workspace durante backup ou restore; aguarde a liberação normal dos locks. Não remova locks. Tenha backup separado e coerente do log `.roadmap/activity.jsonl`, dos contratos ativos e dos registros externos de confiança quando habilitados. O arquivo compactado abaixo contém artifacts e manifesto, **não** contém o log nem chaves. O manifesto registra hash e última sequência do log para identificar o par correto; não confunda a sequência com retenção integral de efeitos.

Sugestão: backup após cada lote de efeitos relevante, antes de migrações, releases e transferência de máquina; ao menos diário quando há escrita contínua. Conserve mais de uma geração fora da máquina e ensaie a restauração periodicamente. Trate backups com a mesma confidencialidade dos dados históricos. A soma de hashes permite detectar corrupção; uma cópia do manifesto junto do arquivo não autentica um adversário que substitua ambos.

O programa mantém o conteúdo da árvore em memória: use-o em árvores que caibam na memória disponível. Para volumes maiores, adote ferramenta de backup com streaming e manifesto equivalente e valide-a antes do uso. Ele rejeita links simbólicos e objetos não regulares; não sobrescreve destino divergente. Uma falha de I/O no restore pode deixar parte dos arquivos iguais já copiada: preserve o erro, corrija a causa e repita no destino limpo ou idêntico.

## 3. Programa reproduzível

Salve o conteúdo seguinte em um arquivo temporário escolhido pelo operador, por exemplo `/tmp/esaa-artifact-backup.py`. Esse arquivo é ferramenta local do procedimento, sem instalação no pacote nem mudança do repositório.

```python
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

mode, root_arg, archive_arg = sys.argv[1:]
root = Path(root_arg).resolve()
archive = Path(archive_arg).resolve()
base = root / '.roadmap/artifacts'
sha = lambda data: hashlib.sha256(data).hexdigest()

if mode == 'backup':
    if not base.is_dir() or base.is_symlink():
        raise SystemExit('artifacts ausentes ou raiz simbolica')
    if archive.exists() or archive.with_suffix(archive.suffix + '.sha256').exists():
        raise SystemExit('escolha um nome novo para o backup')
    files = {}
    content = {}
    for path in sorted(base.rglob('*')):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise SystemExit('tipo nao regular: ' + str(path))
        if path.is_file():
            name = path.relative_to(root).as_posix()
            content[name] = path.read_bytes()
            files[name] = {'size': len(content[name]), 'sha256': sha(content[name])}
    log = (root / '.roadmap/activity.jsonl').read_bytes()
    events = [json.loads(line) for line in log.splitlines() if line.strip()]
    manifest = {'format': 1, 'files': files, 'event_store_sha256': sha(log),
                'last_event_seq': events[-1]['event_seq'] if events else 0}
    payload = json.dumps(manifest, sort_keys=True, indent=2).encode() + b'\n'
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'w:gz') as tar:
        for name, data in [('MANIFEST.json', payload), *content.items()]:
            item = tarfile.TarInfo(name)
            item.size = len(data)
            item.mode = 0o600
            tar.addfile(item, io.BytesIO(data))
    archive.with_suffix(archive.suffix + '.sha256').write_text(sha(archive.read_bytes()) + '\n')
    print(json.dumps({'backup': str(archive), 'files': len(files),
                      'last_event_seq': manifest['last_event_seq']}))
elif mode in {'check', 'restore'}:
    expected = archive.with_suffix(archive.suffix + '.sha256').read_text().strip()
    if sha(archive.read_bytes()) != expected:
        raise SystemExit('hash do arquivo compactado diverge')
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)) or any(not m.isfile() for m in members):
            raise SystemExit('membros duplicados ou nao regulares')
        mf = tar.extractfile('MANIFEST.json')
        assert mf is not None
        manifest = json.load(mf)
        if manifest['format'] != 1:
            raise SystemExit('formato de manifesto desconhecido')
        files = manifest['files']
        if set(names) != {'MANIFEST.json', *files}:
            raise SystemExit('manifesto e membros divergem')
        content = {}
        for name, info in files.items():
            path = PurePosixPath(name)
            if ('\\' in name or path.as_posix() != name or len(path.parts) < 3
                    or path.is_absolute() or '..' in path.parts
                    or path.parts[:2] != ('.roadmap', 'artifacts')):
                raise SystemExit('caminho invalido: ' + name)
            src = tar.extractfile(name)
            assert src is not None
            data = src.read()
            if len(data) != info['size'] or sha(data) != info['sha256']:
                raise SystemExit('bytes divergentes: ' + name)
            content[name] = data
    for name, data in content.items():
        dest = root / name
        if any(p.is_symlink() for p in [dest, *dest.parents]):
            raise SystemExit('destino simbolico: ' + name)
        if dest.exists() and (not dest.is_file() or dest.read_bytes() != data):
            raise SystemExit('destino existente diverge: ' + name)
    if mode == 'restore':
        for name, data in content.items():
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                with dest.open('xb') as output:
                    output.write(data)
    missing = [name for name in files if not (root / name).is_file()]
    if missing:
        raise SystemExit('faltam arquivos locais; execute restore: ' + str(missing[:3]))
    log = root / '.roadmap/activity.jsonl'
    same_log = log.is_file() and sha(log.read_bytes()) == manifest['event_store_sha256']
    print(json.dumps({'mode': mode, 'files_verified': len(files),
                      'last_event_seq': manifest['last_event_seq'], 'same_log': same_log}))
else:
    raise SystemExit('modo deve ser backup, restore ou check')
```

## 4. Backup e conferência

Defina caminhos absolutos; `ESAA_WORKSPACE` é o workspace de origem e `ESAA_BACKUP` é um nome novo fora dele. Substitua os valores ilustrativos. O arquivo `.sha256` será criado ao lado do `.tar.gz`; mantenha ambos. O comando recusa sobrescrever uma geração existente.

```bash
ESAA_WORKSPACE=/caminho/do/workspace
ESAA_BACKUP=/caminho/externo/backup-artifacts-20261112.tar.gz
python /tmp/esaa-artifact-backup.py backup "$ESAA_WORKSPACE" "$ESAA_BACKUP"
python /tmp/esaa-artifact-backup.py check "$ESAA_WORKSPACE" "$ESAA_BACKUP"
```

`backup` inclui cada arquivo regular da árvore e `MANIFEST.json`, com tamanho e SHA-256 por caminho, SHA-256 do log e `last_event_seq`. `check` valida o SHA-256 externo, o conjunto de membros, cada tamanho/hash interno e os arquivos correspondentes no workspace; sucesso informa `files_verified`. Arquivos locais adicionais de lotes posteriores não pertencem a essa geração e não são removidos. `same_log=true` confirma os mesmos bytes de log do backup. `false` é sinal de que se está usando outro estado do log: selecione o par correto antes de recuperação, sem concluir que o backup contém artifacts de eventos posteriores.

## 5. Restauração e conferência de efeitos

Primeiro restaure em uma cópia isolada do workspace, com o log e contratos correspondentes. Não execute recuperação de efeitos externos sem conferir seus destinos e autorização: os artifacts podem referenciar caminhos externos. `ESAA_RESTORE` identifica essa cópia; não use diretórios do checkout real no ensaio.

```bash
ESAA_RESTORE=/caminho/da/copia-isolada
python /tmp/esaa-artifact-backup.py restore "$ESAA_RESTORE" "$ESAA_BACKUP"
python /tmp/esaa-artifact-backup.py check "$ESAA_RESTORE" "$ESAA_BACKUP"
PYTHONPATH=src python -B -m esaa --root "$ESAA_RESTORE" verify
PYTHONPATH=src python -B -m esaa --root "$ESAA_RESTORE" effects recover --dry-run
```

No checkout, execute de sua raiz para `PYTHONPATH=src` apontar para o código inspecionado. Na instalação distribuída, use `python -m esaa` do ambiente instalado, sem o `PYTHONPATH`. `restore` lê membros explicitamente e valida caminhos antes de copiar; não faz extração cega. Se encontrar um artifact local com bytes diferentes, interrompe: preserve a cópia existente para investigação e repita em destino novo. Restore não edita o log, projeções, contratos nem registros de confiança.

Confira `errors` na resposta JSON do dry-run; o status do processo sozinho não substitui essa inspeção. Compare destinos e quantidade com a expectativa do operador. Só então aplique, na cópia de ensaio ou no workspace autorizado:

```bash
PYTHONPATH=src python -B -m esaa --root "$ESAA_RESTORE" --runner human-terminal effects recover
PYTHONPATH=src python -B -m esaa --root "$ESAA_RESTORE" verify
```

Use o identificador do runner real: o ensaio desta entrega usou `--runner codex`. `verify=ok` trata da integridade/projeção e não comprova sozinho a disponibilidade dos artifacts; a inspeção de `errors` no recover continua necessária. Recuperação restaura o último efeito registrado por destino, não todos os estados intermediários ({code('src/esaa/file_effects.py','recover_file_effects')}). Para históricos completos, retenha toda a árvore de artifacts e as gerações adequadas.

## 6. Perda definitiva

Se não houver cópia dos artifacts, procure backup da máquina ou outra réplica comprovadamente correspondente. Não invente conteúdo a partir do SHA-256, não recrie um artifact histórico usando só o arquivo atual e não edite eventos para eliminar o erro.

Registre o caminho afetado, sequência/evento, `artifact_path` e erro `ARTIFACT_MISSING` pela CLI de issue report aplicável, com evidência; o runner real deve ser identificado em qualquer comando que escreva evento. Preserve o log para auditoria. Um arquivo final existente pode ser preservado como evidência, mas não prova todos os bytes históricos perdidos. Caso o conteúdo precise ser reconstruído para o trabalho atual, faça uma nova entrega governada autorizada; ela não restitui a proveniência do artifact antigo. Declare a recuperação histórica indisponível para aqueles efeitos.

## 7. Evidência do procedimento

Ensaio real em 12/11/2026, na base 0.5.0b29, com workspace descartável gerado por bootstrap/init e duas tarefas completadas via CLI. O conjunto incluiu um efeito UTF-8 e um binário de 9 bytes; o backup preservou **3 arquivos** (dois JSONs de artifact e um blob). A cópia do log terminava em **24**, hash de projeção `bb6dac6d1c772548d54034da11f326518717a456e40de77f6816ccd8175b89d1`.

Antes do restore, `effects recover --dry-run` retornou dois `ARTIFACT_MISSING`. Depois do restore e check, os 3 arquivos passaram no manifesto; o dry-run indicou 2 destinos recuperáveis e zero erros. A aplicação recuperou os 2 arquivos, com os mesmos bytes de origem, e `verify` permaneceu ok com sequência e hash idênticos. Um segundo restore de bytes idênticos foi aceito. Alteração do arquivo compactado foi recusada pelo SHA-256 externo. Esses resultados demonstram o procedimento local; não atestam backups remotos, custódia real de chaves ou máquinas de produção.

## Referências

**Este documento referencia:**

- [adr-0004](../adr/0004-artifacts-fora-git.md) — artifacts fora do Git e consequências para clones.
- [file_effects.py](../../src/esaa/file_effects.py) — funções de artifacts e recuperação citadas no texto.
- [gitignore-esaa](../../.gitignore) — exclusão da árvore de artifacts.
- [modelo-ameacas](../security/threat-model.md) — base confiável e limites de efeitos externos.
- [seguranca-esaa](../../SECURITY.md) — suporte e reporte.

**Este documento é referenciado por:**

- [indice-adrs](../adr/README.md), [adr-0004](../adr/0004-artifacts-fora-git.md) e [seguranca-esaa](../../SECURITY.md) — operação e preservação de efeitos.
