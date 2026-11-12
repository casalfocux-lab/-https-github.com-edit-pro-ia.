# Edit Pro IA

Editor de vídeo automático para conteúdo vertical (Reels, TikTok, Shorts), operado por comandos.

## Recursos
1. **Corte de silêncios e pausas**, automático
2. **Formato** 9:16, 16:9, 1:1 ou 4:5, com ajuste da posição do corte
3. **Áudio nivelado** em -14 LUFS (padrão das redes sociais)
4. **Música de fundo com ducking**: abaixa sozinha quando há fala
5. **Legendas**, automáticas (Whisper) ou a partir de um `.srt`
6. **Logotipo** em qualquer canto
7. **Processamento em lote** de uma pasta inteira

## Instalação
Requer Python 3.10+ e ffmpeg.
```bash
pip install -r requirements.txt
```

## Uso
```bash
# Analisar um vídeo (quanto silêncio será cortado)
python -m editpro info bruto.mp4

# Editar um vídeo
python -m editpro process bruto.mp4 -o pronto.mp4 --music trilha.mp3 --logo logo.png --captions auto

# Editar uma pasta inteira
python -m editpro batch input/ output/ --captions auto --max-duration 80
```

Principais opções: `--format`, `--crop-x` (0 = esquerda, 0.5 = centro, 1 = direita), `--silence-db`,
`--min-silence`, `--no-cut`, `--music-volume`, `--logo-pos tr|tl|br|bl`, `--captions none|auto|arquivo.srt`,
`--max-duration`. Veja todas com `python -m editpro process -h`.

## Estrutura
- `editpro/`: código do editor
- `agent/AGENT.md`: instruções do agente de edição
- `input/` e `output/`: pastas de trabalho (vídeos não vão para o git)
