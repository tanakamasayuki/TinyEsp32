# 処理別分析の測定記録

結果の解釈は [処理別ビルド費用と設定の自由度](../../../build-cost-analysis.ja.md) を参照。

## データ

| ファイル | 内容 |
| --- | --- |
| compile-summary.json / compile-raw.json | 通常フラグで61翻訳単位を各3回。コア60本と最小スケッチ1本 |
| gcc-phase-summary.json / gcc-phase-raw.json | 同じ翻訳単位を `-ftime-report` 付きで各3回。通常計測と混ぜない |
| header-summary.json / header-raw.json | 13通りの include を各5回。通常フラグ |
| option-summary.json / option-raw.json | 基準と6通りの変更による、60ソースの前処理結果の比較 |
| pipeline.json | 初回1回、変更なし3回、定数変更3回。ツール別 CPU、開始・終了、実コマンド |
| object-closure.json | 通常計測の `.o` の code/literal 量と非 system header の依存 |
| map-summary.json | 最小 ELF の保持された section と archive / object の対応 |
| frozen-config.json | SDK の三つの設定へ `-D` を渡したときの実際の値 |

CPU 時間は user + system、秒単位。通常のコンパイル測定に GCC の工程計測を入れない。`gcc-phase-*` は原因を調べる補助測定で、オーバーヘッドを含む。

map は discarded section より後だけを読み、文字列マージと同一アドレス範囲の重複を共有として扱う。共有データをある一つの archive の削減可能量と見なさない。`object-closure.json` の `has_functional` は `-MMD` に system header が出ないため、この環境では依存の有無の判断に使えない。

## 再現

先に [前段の測定手順](../../../build-performance-survey.ja.md) で新しい調査ディレクトリを作り、`measure.py` を実行する。そのディレクトリを以下の `survey_dir` に指定する。

```bash
deep_dir=$(mktemp -d /tmp/tinyesp32-deep-XXXXXX)
arduino-cli compile --profile s3 --show-properties=expanded "$survey_dir/Minimal" > "$survey_dir/properties.txt"
python3 docs/research/2026-11-22/deep/profile_compile.py "$survey_dir/build/compile_commands.json" "$deep_dir/compile" --plain
python3 docs/research/2026-11-22/deep/profile_compile.py "$survey_dir/build/compile_commands.json" "$deep_dir/gcc-phases"
python3 docs/research/2026-11-22/deep/profile_headers.py "$survey_dir/build/compile_commands.json" "$deep_dir/headers"
python3 docs/research/2026-11-22/deep/profile_options.py "$survey_dir/build/compile_commands.json" "$deep_dir/options"
python3 docs/research/2026-11-22/deep/profile_pipeline.py "$survey_dir" "$deep_dir/pipeline"
```

`profile_pipeline.py` は `trace_tool.py` を自動コピーする。`profile_headers.py` の ArduinoCore-API 比較は `/home/mt/dev_wch/ArduinoCore-CH32RV/cores/arduino/api/ArduinoAPI.h` を使うため、別環境ではその固定版のパスを指定し直す。

map の分析は、実際の ELF と、それを作った map を一組で指定する。

```text
python3 profile_map.py LINK_MAP ELF SIZE_TOOL OUTPUT_JSON
```

このスクリプト群は今回の S3 / Xtensa とログ形式に対応する調査用コード。任意のチップ・platform・ログ形式を扱う汎用プロファイラーではない。CLI と toolchain の版、FQBN、SDK の版を変更した結果は、元の測定と分けて記録する。
