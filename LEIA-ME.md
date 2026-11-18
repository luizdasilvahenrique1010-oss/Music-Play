# JukeOS – ISO do PLAY MUSICA (Jukebox Karaoke)

Liga o PC pelo pendrive -> abre direto o jukebox em tela cheia (sem barra, sem Linux na tela), com som.

## O que tem aqui
- `jogo/`  -> seus arquivos (index.html, INICIAR.bat, atualizar.ps1, LEIA-ME.txt). Coloque aqui tambem a pasta **som** (com credito.mp3) e, se quiser, a pasta **imagem** (capas pequenas).
- `jukeserver.py` -> servidor interno do sistema (porta 8765): lista e monta pendrives/HDs sozinho, entrega musicas e capas. Substitui o atualizar.ps1 (a lista e gerada na hora, nao precisa rodar nada).
- `slotgame` -> inicializador (sobe som, video, servidor e o navegador em tela cheia). O nome ficou igual ao kit anterior de proposito.
- `build.sh`, `build.yml`, `mkimg.slotos.sh`, `genapkovl-slotos.sh`, `INSTALAR.bat` -> montagem da ISO (mesmos nomes do kit anterior; so substituir).

## ONDE FICAM AS MUSICAS (importante)
Musica em video/MP3 e muito grande: **NAO ponha a pasta musicas dentro do GitHub nem da ISO** (o sistema roda na memoria RAM).
Coloque as pastas **musicas** e **imagem** no pendrive/HD:
- Com Ventoy: na particao grande do pendrive (a mesma onde esta a ISO), crie `musicas/` e `imagem/` ao lado da ISO.
- Ou use um segundo pendrive/HD so com as pastas `musicas` e `imagem`.
Ao ligar, o sistema acha o pendrive sozinho. Se houver apenas 1 fonte com pasta "musicas", ele carrega direto. Senao abre a tela de Bibliotecas (F2 -> Bibliotecas) para escolher. Plugou depois? F2 -> Bibliotecas -> Atualizar.
Formatos de pendrive aceitos: FAT32, exFAT, NTFS, ext4 (somente leitura, nao estraga nada).
A pasta `imagem` e a `som` podem ficar dentro da ISO (em `jogo/`) se forem pequenas (ate umas centenas de MB no total).

## COMO MONTAR (GitHub, igual antes)
1. No repositorio, apague os arquivos antigos do kit e envie TODOS os arquivos desta pasta (inclusive a pasta `jogo`), mantendo `build.yml` dentro de `.github/workflows/`.
2. Aba Actions -> "Montar ISO JukeOS" -> Run workflow. Espere ~10 a 25 min.
3. Baixe o artefato **jukeos-iso**, extraia o .iso. Grave com Rufus (modo DD) ou copie para o Ventoy.
(Ou no Windows com Docker: duplo clique em INSTALAR.bat; a ISO aparece em Downloads\JukeOS-ISO.)

## Requisitos do PC
- 64 bits, **2 GB de RAM ou mais** (o sistema carrega na RAM).
- Som: placas Intel HDA, USB e a maioria das onboard (ALSA + PulseAudio, volume no maximo no boot).
- Video: Intel, AMD, NVIDIA/VM via drivers abertos (Mesa); se a placa falhar, o sistema liga sozinho o modo por software.
- Se der problema: Alt+F2 abre um terminal (login root, sem senha no live) – ou tire foto da tela e mande.

## Limitacoes conhecidas
- As configuracoes do jukebox (valor, ranking, teclas) ficam na memoria e **voltam ao padrao ao reiniciar**. Se quiser fixar, edite os valores padrao no index.html (DEF_KEYS / cfg).
- A ISO foi testada aqui apenas no servidor e no navegador (musica, capas, pendrive simulado). O boot real em hardware precisa do seu teste.
