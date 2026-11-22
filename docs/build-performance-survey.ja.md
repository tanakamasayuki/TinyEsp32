# ESP32 Arduino のビルド時間と軽量化の調査

調査日: 2026年11月22日。対象はビルド時間を中心に、生成物の Flash 使用量、RAM、既存ライブラリとの互換性、継続的な保守まで含める。

## 判断の要点

**実装方式を選ぶ前に、コンパイル費用、保持されるコード量、設定を変更できる範囲を別々に比較する。** ソースごとの CPU 時間、ヘッダー除去、オプションの影響範囲、最終 ELF の内訳は [処理別の定量分析](build-cost-analysis.ja.md) にまとめた。本書は変更するレイヤーごとの実現性と保守範囲を扱う。

この環境の ESP32-S3 向け最小スケッチでは、コアを含む初回ビルドは34.8秒だった。同じビルドディレクトリでは5.8〜6.2秒となり、コア60ファイルの再コンパイルはゼロだった。スケッチの `delay(1)` を `delay(2)` に変えてもコアは再利用され、12.6秒だった。「コアは毎回ビルドするもの」という前提を変えるだけで改善する余地がある。

一方、`Arduino.h` を1回含むだけの C++ ファイルは、前処理後に約206万バイト、約6.9万行、430回のヘッダー読み込みになった。**重い実装を全部ヘッダーに移すと、この解析を各翻訳単位で繰り返すため、ビルドがかえって遅くなる場合がある。** 小さな inline 実装、必要な機能だけを選ぶ構造、薄い宣言、コンパイル済みライブラリを組み合わせる方がよい。

互換性には少なくとも次の二つがあり、TinyEsp32 でどちらを採用するかは未決定である。

- **現行 ESP32 実装との互換**: 内部 HAL、暗黙 include、固有型、起動時の振る舞い等も、対象範囲を決めて再利用する。
- **Arduino API への準拠**: 一般の Arduino API とその意味を維持し、ESP32 固有の内部設計は作り直せる。現行実装の癖を再現することを必須条件にしない。

ビルド時のオプションが実装を変える部分は、単一の事前ビルド済み archive に固定できない。キャッシュキーを増やすことは正しい再利用には役立つが、設定自由度の問題は解消しない。現在の SDK が既に固定している設定も含めて、ソース供給・小さい設定用翻訳単位・実行時設定を比較する。

無線を維持しながら ESP-IDF の実行時基盤まで置き換える案は可能性があるが、ビルド高速化よりもプラットフォーム開発に近い。GPIO、Serial、SPI、I2C だけを対象にする場合とは難易度が大きく異なる。

## 調査対象と測定の範囲

### ローカルで確認した版

| 対象 | 確認した内容 |
| --- | --- |
| Arduino CLI | 1.5.1、commit `01f3d4f2b` |
| 計測した Arduino platform | `esp32:esp32` 3.3.13 |
| ボード | `esp32:esp32:esp32s3`、既定オプション、4並列 |
| SDK の記録 | lib-builder `c26041d`、ESP-IDF `release/v5.5 a45de8ccca1`、Arduino `65d29ddf3` |
| ローカル lib-builder | `/home/mt/dev/esp32-arduino-lib-builder`、`c26041da7e672c6984babbd76de855474283631c` |
| 比較した CH32 コア | `/home/mt/dev_wch/ArduinoCore-CH32RV`、調査時 HEAD `42bd72f02e0db6616e2466c8bad29289989abd6a` |
| ホスト | Intel N100、メモリ約15 GiB、Linux |

ESP32 platform とツールは `~/.arduino15/internal/` に profile 用として存在した。`arduino-cli core list` が空でも未インストールとは判断できない。実際に解決された platform・SDK・compiler の絶対パスとソースの SHA-256 は [inventory.json](research/2026-11-22/inventory.json) に保存した。

このワークスペースには 4.0.0 系や他の3.3系もあるが、測定値は上表の組み合わせの値である。例えば `EspHelper` の既存 profile には3.3.6の指定があり、そちらの性能を直接測った値ではない。公式ドキュメントの `latest` も、この SDK と一致するとは限らない。

時間は実機への書き込みを含まない、CLI の起動から終了までの壁時計時間。同じホストで CH32 のハードウェアテスト等も動いており、排他的なベンチマークではない。特に後半の測定は別の調査用処理とも一部重なった。速度の普遍的な倍率ではなく、**何を再コンパイルしたか、どの工程が残ったか**を判断する値として扱う。

### 最小スケッチの結果

```cpp
void setup() {}
void loop() { delay(1); }
```

| 条件 | 合計秒 | コアのコンパイル数 | スケッチのコンパイル数 | 読み取れること |
| --- | ---: | ---: | ---: | --- |
| 空の明示 build-path で初回 | 34.791 | 60 | 1 | 未使用機能のファイルもコアとして処理する |
| 同じ build-path で変更なし | 6.249 | 0 | 0 | コアとスケッチのオブジェクトを再利用できる |
| さらに変更なし | 5.842 | 0 | 0 | 再利用しても一定の処理が残る |
| 同じ build-path で delay の値だけ変更 | 12.649 | 0 | 1 | 小変更でも前処理・コンパイル・リンク等は残る |
| 別の空の明示 build-path | 36.833 | 60 | 1 | この CLI では標準の共有コアキャッシュを使わない |
| build-path を省略して初回 | 62.843 | 60 | 1 | 共有キャッシュを作成した。時間は並行負荷の影響を含む |
| 省略したまま同じスケッチ | 6.963 | 0 | 0 | `Using precompiled core` を確認 |
| 省略したまま別スケッチ | 11.805 | 0 | 1 | 別スケッチでも同じ共有 core.a を使用 |

出典: [build-measurements.json](research/2026-11-22/build-measurements.json)。前半の明示 build-path は `/tmp`、既定キャッシュはホーム配下で、ファイルシステムの条件も異なる。

初回34.8秒の verbose 出力からの概算では、コア処理開始からリンク開始まで約22.7秒、リンク開始からアプリの `elf2image` 開始まで約2.9秒だった。変更なしの再実行でもリンクに入り、bootloader の `elf2image`、アプリの `elf2image`、パーティション生成、`merge-bin` を実行していた。これらの区間は CLI 出力の観測時刻であり、個々の子プロセスの厳密な CPU 時間ではない。

## 仮説をゼロベースで検討する

| 仮説 | 今回の結果と判断 |
| --- | --- |
| ESP-IDF のソースを毎回コンパイルしているから遅い | 計測した通常の Arduino ビルドでは SDK の `.a` を使用。IDF 再コンパイルは主要因ではない |
| コアは毎回コンパイルする必要がある | 不要。同一 build-path のオブジェクト再利用と、標準の共有 core.a 再利用の両方を確認 |
| コアが大きいので初回が遅い | 一部支持。最小スケッチでも60ファイルをコンパイルした。ただし実装量だけでなく include の重さも効く |
| ヘッダー中心にすればビルドも必ず速い | 支持しない。不要な翻訳単位は減らせるが、使用する側の解析・最適化コストは増えうる |
| 未使用コードは既にリンクから全部消える | 支持しない。実行時の条件分岐、初期化、強制シンボル、コンストラクターが参照を残す |
| 大量の IDF ライブラリが全部 Flash に入る | 誤り。リンク入力の数と、最終的に残るコード量は別。既に section GC が有効 |
| SDK を小さくすれば通常のビルドが必ず大幅に速くなる | 条件付き。SDK 自身のコンパイルは既に省略されている。ヘッダー・リンク・初期化への影響で判断する |
| IDF をなくせば最善 | 用途次第。最短ビルドは狙えるが、無線や既存 IDF 利用ライブラリの移植費用が大きい |

最初に記録したい式は次である。

```text
待ち時間 = 環境と依存関係の準備
         + スケッチの変換とライブラリ探索
         + 前処理と C/C++ の解析
         + コード生成と最適化
         + アーカイブ作成
         + リンク
         + 書き込み用イメージ生成とコピー
```

この各項について、初回、変更なし、スケッチ変更、公開ヘッダー変更、コア変更、ボード設定変更を分ける。Flash 使用量、RAM 使用量、インストール容量、ビルド時間も別の指標にする。

## 実際のレイヤーと依存関係

`esp32-arduino-lib-builder` は独立した実行時ライブラリ層というより、**IDF と追加コンポーネントから SDK を生成・梱包する工程**である。

```text
SDK を作る工程
  ESP-IDF ソースと無線等の配布バイナリ
  追加コンポーネントと Arduino のビルド設定
       ↓ lib-builder または独自の CMake と梱包処理
  .a + sdkconfig.h + 公開ヘッダー + linker script
     + compile/link flags + bootloader とメモリ別の生成物

通常のアプリを作る工程
  スケッチとユーザーライブラリ
       ↓ Arduino CLI の変換と探索
  Arduino コアと上記 SDK のヘッダーでコンパイル
       ↓ core.a と SDK の .a をリンク
  ELF → アプリ bin とパーティション等 → 書き込み
```

ローカルの `copy-libs.sh` は IDF プロジェクトのコンパイル・リンク情報から SDK を抽出し、ライブラリ収集時に `main` と `arduino` を除外している。Arduino コアが通常のスケッチ側で別途ビルドされるのは、この境界による。[lib-builder の SDK 抽出処理](https://github.com/espressif/esp32-arduino-lib-builder/blob/c26041da7e672c6984babbd76de855474283631c/tools/copy-libs.sh)

手を入れられる場所は、少なくとも次のように分かれる。上下の順は改造の優先順位を意味しない。

| 場所 | 変更候補 | 主に減るもの |
| --- | --- | --- |
| 開発機と実行環境 | 適切な並列数、ローカルの保存先、メモリ不足の回避 | I/O 待ち、CPU 待ち |
| profile と呼び出し方 | バージョン固定、毎回の clean・一時 build-path の回避 | 不要な再ビルドと環境取得 |
| キャッシュ | CLI の共有 core.a、ccache、CI の保存と復元 | 同じ仕事の繰り返し |
| スケッチの変換と探索 | `.cpp` 化、明示した依存関係、別のビルドフロントエンド | 自動探索と prototype 生成 |
| 公開ヘッダー | forward declaration、include の限定、内部型の隠蔽 | 使用側の解析と変更時の再ビルド |
| コアのコンパイル単位 | 機能分割、選択コンパイル、事前コンパイル、PCH | 初回・変更時のコンパイル |
| Arduino の実行時設計 | 遅延初期化、起動診断の除去、周辺の所有権管理の簡素化 | 到達するコード、初期化、RAM |
| リンク構成 | 不要参照の除去、正しい archive 境界、必要に応じた LTO | リンク時間、最終コード量 |
| 出力工程 | bootloader・partition・merged bin の入力追跡 | 変更がない生成処理 |
| SDK の生成設定 | sdkconfig、追加コンポーネント、例外等の設定 | SDK 生成、参照、実行時資源 |
| SDK の生成と配布方式 | 独自のエクスポーター、用途別 SDK、再現可能な manifest | 配布量、設定の複雑さ |
| IDF のコンポーネント境界 | 必要な依存だけにする、独自 component を作る | コンポーネントのビルドと公開依存 |
| RTOS とシステム基盤 | FreeRTOS 維持、限定利用、別 runtime への置換 | 実行時資源と基盤依存 |
| HAL とチップ依存 | IDF driver、HAL/LL、直接レジスターの選択 | ラッパー層と対象ソース |
| 起動と無線の基盤 | startup、割り込み、ROM、無線 OS 接続の置換 | IDF への依存そのもの |

## ソースから分かる重さの原因

### 未使用機能もコアのコンパイル対象になる

Arduino CLI はコアディレクトリ以下のソースを列挙してコンパイルする。スケッチの呼び出しから「使用するコアの `.cpp` だけ」を自動的に選ぶ仕組みではない。[CLI 1.5.1 の core.go](https://github.com/arduino/arduino-cli/blob/v1.5.1/internal/arduino/builder/core.go)、[compilation.go](https://github.com/arduino/arduino-cli/blob/v1.5.1/internal/arduino/builder/compilation.go)

今回のコアには C が34本、C++ が26本あり、すべてコンパイルされた。USB やチップによって不要な周辺実装は `#if` で本文が消える場合もあるが、ファイル処理や条件より前にある include のコストまで必ずゼロになるわけではない。

ただし CH32 コア側にも、C 70本、C++ 32本、アセンブリ2本があった。API の固定コピーを含む単純なファイル集計であり、ESP32 の方がファイル数が多いという説明は成り立たない。CH32 の良さは、小さな実装、チップに近い依存、独立したインスタンス、必要な機能だけをリンクする境界にあると考えられる。両コアの速度を直接比較したベンチマークではない。

### Arduino.h の公開依存が広い

`Arduino.h` は FreeRTOS、`esp32-hal.h`、STL の algorithm・cmath、String、Stream、IPAddress、Client、Server、Udp、HardwareSerial、Esp 等を含む。`esp32-hal.h` も多数の周辺ヘッダーを含み、`HardwareSerial.h` は `<functional>` と USB のヘッダーを含む。[Arduino.h 3.3.13](https://github.com/espressif/arduino-esp32/blob/3.3.13/cores/esp32/Arduino.h)

同じコンパイルオプションで、空に近い C++ ファイルの include を変えた結果は次のとおり。

| include | 前処理出力バイト | 前処理出力行数 | `-H` で観測した include 回数 |
| --- | ---: | ---: | ---: |
| `stdint.h` | 6,461 | 229 | 7 |
| `Arduino.h` | 2,062,821 | 68,608 | 430 |

`-H` は include イベントの数で、一意なファイル数とは限らない。前処理出力の大きさも、最終 Flash 使用量とは異なる。各3回の探索的計測では `Arduino.h` 側のコンパイルは2.88〜6.91秒と変動したため、厳密な速度倍率にはしない。[header-link-measurements.json](research/2026-11-22/header-link-measurements.json)

SDK の include response file には390の検索パス指定があった。全パスの全ヘッダーを読むわけではないが、検索と依存の境界が広い。最初に効く候補は巨大なヘッダー実装の追加ではなく、**小さな公開宣言から必要な内部実装だけを見る構造**である。

### 実行しないコードにもリンク上の参照がある

既定の `shouldPrintChipDebugReport()` は weak な関数で `false` を返す。しかし `loopTask()` には、この関数の結果によって `printBeforeSetupInfo()` と `printAfterSetupInfo()` を呼ぶコードがある。別の定義で上書きできる実行時の条件なので、通常の非 LTO ビルドでは呼び出し先を消しきれない。[main.cpp 3.3.13](https://github.com/espressif/arduino-esp32/blob/3.3.13/cores/esp32/main.cpp)

最小スケッチの map と `nm` でも診断関数、`Esp` 関連の参照、`String` のコンストラクター等を確認した。map 冒頭の「archive member が取り出された」記録だけでは section GC 後に残った証拠にはならないため、最終 ELF のシンボルも確認した。

同じコアと SDK を用い、二つの診断関数を空の関数で先に解決するリンク実験では、次の結果になった。

| 条件 | アプリ bin のファイルサイズ |
| --- | ---: |
| 元の最小スケッチ | 253,360 B |
| 診断関数を空にしたもの | 244,384 B |
| 差 | 8,976 B |

この実験では `String` の該当コンストラクターは消えたが、`_dtoa_r`、`_vfprintf_r`、`_svfprintf_r` は残った。「診断を消せば浮動小数 printf もすべて消える」とは言えない。元の CLI が表示したプログラム使用量253,211 Bと、上表の bin ファイルサイズは計算対象が異なる。[debug-report-probe.json](research/2026-11-22/debug-report-probe.json)

これはリンクと生成物の確認で、実機動作やビルド時間の改善は検証していない。フォークでは診断の呼び出しをコンパイル時に除外する設計が候補になる。

### SDK のアーカイブ数と Flash 使用量は比例しない

この S3 SDK の直下には169本の `.a` があった。`ld_libs` には730回の `-l` 指定があり、異なる名前は175個だった。追加の探索先もあるため、この二つの数は一致しない。同じライブラリの繰り返しにはリンク順序や循環依存を解決する役割があり、単純に重複を削るのは適切ではない。

既に `-ffunction-sections`、`-fdata-sections`、`--gc-sections` が使われ、LTO はこの組み合わせでは無効だった。一方、`-u` で強制される startup・VFS・C/C++ runtime・各種 wrapper や初期化関数はある。`KEEP` されたセクションや初期化配列も含め、これらは「呼んでいないのに残る」を調べる場所である。

`--cref` の有無を変えたリンク再実行も行ったが、並行負荷の変動が大きく、削除による速度差は確定できなかった。リンク入力や診断出力を減らす案は、コアの再コンパイル削減とは別に評価する。

## 案1 いまの仕組みのまま軽くする

**実現性は高い。現状の費用を測る対照構成として有用だが、SDK の設定固定やコアの公開依存は残る。** API と SDK の互換性をほぼ維持できる。

### コアを作り直している条件を取り除く

同じスケッチの反復開発では、ビルドディレクトリを安定させる。大量の別スケッチをビルドする場合は、まず `--build-path` を省略して標準の共有コアキャッシュを使えるかを確認する。新しい空の build-path を毎回作る運用は、今回の CLI ではコアの作り直しになった。

CLI 1.0.4以降は、明示した build-path ではその場所で全ビルドを行い、グローバルのコアキャッシュを使わないという仕様変更がある。古い記事の `--build-cache-path` をそのまま導入せず、使っている CLI の仕様を確認する。[Arduino CLI の移行情報](https://docs.arduino.cc/arduino-cli/UPGRADING/)

verbose ログで以下を見分ける。

- `Using previously compiled file`: そのビルド先の `.o` 等を再利用。
- `Using precompiled core`: 共有キャッシュの core.a を再利用。
- コンパイラーの `-c .../cores/esp32/...`: 実際にコアを再コンパイル。

併せて、常時 `--clean`、ビルド先の削除、FQBN・DebugLevel・USB/PSRAM 設定の頻繁な切り替え、毎回変わる build-property、core のテキスト設定の再生成、SDK やソースのタイムスタンプ変更を調べる。`build.options.json` と前回コマンドの差も有効である。

共有キャッシュは任意の独自フラグの組み合わせを完全に識別する汎用アーティファクト管理ではない。1.5.1 の共有 core.a の名前は FQBN、最適化指定、コアのパスを基に作られる。特に `build_opt.h`、外部 SDK、独自マクロを変えて試すときは、固定 build-path の分離や意図した clean も使い、誤った再利用を防ぐ。[CLI のキャッシュ実装](https://github.com/arduino/arduino-cli/blob/v1.5.1/internal/arduino/builder/core.go)

キャッシュを CI から復元する場合も、CLI・platform・toolchain・SDK・ボード設定・独自フラグの版を揃える。標準キャッシュの保存先、寿命、追加探索先は `build_cache` 設定で管理できる。[CLI configuration](https://docs.arduino.cc/arduino-cli/configuration/)

### 手元のテスト用プラグインで該当する箇所

`/home/mt/dev/pytest-embedded-arduino-cli/src/pytest_embedded_arduino_cli/app.py` では、`resolve_build_path()` が既定で `<sketch>/build/<profile>` を選び、`build_command()` が常に `--build-path` を付けている。調査時の commit は `deabaacd423ba6787586f01afc91d87b2e6a1dab`。[該当する実装](https://github.com/tanakamasayuki/pytest-embedded-arduino-cli/blob/deabaacd423ba6787586f01afc91d87b2e6a1dab/src/pytest_embedded_arduino_cli/app.py)

この経路で多数の ESP32 スケッチをビルドするなら、同じスケッチの再実行では `.o` を再利用できても、各スケッチの初回では共有 core.a の利点が得られない。今回測定した「空の明示 build-path」と同じ問題が起きる構造であり、最初に調べる具体的な候補になる。

プラグインは profile の fingerprint が変わった場合や記録がない場合に `--clean` も付ける。古いライブラリのヘッダーで作った `.o` と新しいライブラリの組み合わせを避ける意図があり、この clean だけを無条件に消すのは適切ではない。出力先を取得する方法を変えて CLI の既定キャッシュを使う、またはこのプラグイン経由でも ccache や事前コンパイル済みコアを使う、といった変更を比較する。

### ユーザーコードとビルド環境を整える

周辺ライブラリの公開 `.h` で、単なる整数型のために `Arduino.h` を含めない。`Print`、`Stream`、`String` 等が必要な場合も、必要な宣言だけを公開し、IDF の具体型を内部 `.cpp` に閉じる余地を調べる。テンプレートが定義を必要とする部分は残す。

大量の自動テストでは、profile の版を固定し、取得済みの依存を再利用する。すでにコンパイル済みの `.a` があっても、profile の解決、展開、コピー、ビルドディレクトリ作成で待つ可能性はある。

並列数は CPU 数だけでなくメモリの余裕で決める。複数スケッチを並列にし、その各スケッチも最大並列にすると、プロセスとメモリ消費が掛け算になる。今回のホストでも他の処理と swap の使用があった。最適な並列数は、同じ負荷条件で比較する。

### ccache と出力工程の改善

CLI のコアキャッシュで不足する場合、compiler wrapper として ccache を接続する。特に、多数の作業ディレクトリや CI ジョブから同じソースをコンパイルする用途で有効。リンクや `elf2image` は速くならず、初回も速くならない。絶対パス、作業ディレクトリ、生成ヘッダー、マクロ等が hit 率を下げるため、まず統計を見る。[ccache manual](https://ccache.dev/manual/latest.html)

lib-builder 自身に ccache が有効でも、通常の Arduino CLI の compiler recipe がその ccache を通るわけではない。今回の環境では PATH 上の ccache は見つからず、速度効果は計測していない。

もう一つの小規模な変更は platform recipe の生成処理である。bootloader は入力 ELF・flash 設定が同じなら再利用し、partition も入力を追跡する。通常のアプリ書き込みで不要なら `merged.bin` は配布時にだけ生成する。これはコアのソースを作り替えずに行えるが、独自の recipe またはビルド処理が必要になる。依存入力を確認せず「出力が存在したらスキップ」とすると、設定変更を取りこぼす。

**限界**: 初回の60ファイル、`Arduino.h` の重さ、Arduino の初期化による依存は基本的に残る。まずこの案で毎回の再コンパイルをなくし、その後に残る時間を見る。

## 案2 現行コアをフォークして軽くする

**実現性は高い。上流互換をどこまで保つかによって、効果と保守費用が変わる。**

最初の変更対象は、起動診断のコンパイル時切り替え、ヘッダー依存の整理、オブジェクトや処理の分割、初期化を必要時まで遅らせること。今回の診断関数の実験は、少なくとも一つの削減余地を具体的に示している。

次に、USB、周辺 HAL、ネットワーク関連型、統計、診断等を小さなモジュールに分ける。現行 CLI のコア直下に `.cpp` を残したまま分割するだけでは、全ファイル列挙は続く。未使用分のコンパイルを止めるには、Arduino ライブラリへの移動、薄いヘッダーと事前コンパイル済み archive の組み合わせ、または明示したソース一覧を使うビルド処理が必要になる。

CH32 側では `HardwareSerial0.cpp` 等がインスタンスごとに分かれ、`Serial` を参照したときだけそのメンバーを archive から取り出す設計になっている。このような「名前を使ったときに初期化も入る」境界は ESP32 側でも検討できる。全インスタンスと初期化を同じ `.o` に入れるより、不要な依存を切りやすい。

ただし ESP32 の Peripheral Manager は、GPIO と UART・PWM 等が同じ端子を使う際の解除処理や所有権を管理している。直接レジスターアクセスに置き換えるなら、「`pinMode()` が以前の周辺機能を解除する」といった挙動をどう維持するか決める。削除してよい単なる重複層とは限らない。

公開 `Arduino.h` を薄くすると、これまで間接 include で使えていた `WiFi` 周辺型や標準ライブラリ型をユーザー側で include する必要が出る。互換版と最小版を明確に分ける方が、暗黙の非互換を混ぜるより管理しやすい。

LTO は、コア内部の到達性や定数伝播を改善できる候補だが、リンク時間を増やすことがある。既存 SDK の機械語 `.a` の内部まで最適化できるわけではない。この SDK はリンク flags に `-fno-lto` を含むため、コンパイル側だけ `-flto` を足す変更では評価にならない。weak、alias、wrapper、IRAM 配置を含めて確かめる。

**限界と保守**: IDF API 更新、チップ追加、Peripheral Manager、USB、起動手順の差分を取り込み続ける必要がある。削除したAPI、遅延した初期化、互換性を維持するAPIを一覧にし、上流への差分を小さく保つ。

## 案3 同じ SDK に独自の Arduino コアを載せる

**限定した API から始めれば十分実現可能。Arduino API を維持しながら内部を変える比較対象になる。**

SDK の `.a`、同じ設定のヘッダー、linker script、bootloader を使い、その上の Arduino API と周辺ラッパーを独自実装する。ArduinoCore-API の Print・Stream 等を再利用する構成は、ローカルの CH32 コアにも実例がある。

最小構成は、`app_main()`、必要な初期化、`setup()` / `loop()`、時間関数、GPIO、Serial、割り込みから始める。SPI・Wire・PWM・ADC は個別モジュールとして追加する。公開ヘッダーに IDF driver や FreeRTOS の具体型を広く漏らさず、小さな宣言と明確な機能境界を持たせる。

同じ SDK を使うなら、FreeRTOS は既存起動基盤として残る。専用の Arduino loop task を作るか、IDF の main task 上で loop を動かすかは選べるが、後者では setup のブロッキング、task の優先度・stack、watchdog の扱いが変わる。単に `app_main()` を差し替えただけで RTOS の費用が消えるわけではない。

### SDK とコアの境界で必要な処理

- `sdkconfig.h` と実際の `.a` の一致、同じチップ・ABI・toolchain・メモリ設定。
- IDF の startup から呼ばれる `app_main()` と、C++ コンストラクターの実行。
- SDK の linker flags が期待する panic・Bluetooth memory release・Matter 等の wrapper。不要なら参照と flags を含めて再設計する。
- PSRAM と heap、時間、割り込み、CPU 周波数、watchdog、必要な NVS の初期化責任。
- `ARDUINO_ARCH_ESP32`、ボードの pin 定義、`IRAM_ATTR`、Print/Stream/String 等の互換範囲。

たとえばこの SDK の flags は `setup()` / `loop()` や Arduino 側 wrapper を強制参照する。独自コアに変えても、その flags を無条件で使えばリンクが成立するとは限らない。**`.a` を同じにすることと、Arduino 向けの link recipe を丸ごと無変更で使うことは別**である。

### 既存ライブラリとの互換性

| 利用するもの | 移行の見通し |
| --- | --- |
| GPIO、Serial、Print/Stream、SPI、Wire の一般 API | 実装すれば再利用しやすい |
| Arduino ESP32 固有の Esp クラス、HAL、Peripheral Manager | 互換ラッパーかライブラリ側の変更が必要 |
| IDF / FreeRTOS を直接使うライブラリ | 同じ SDK は有利。ただし必要な初期化と API 設定が必要 |
| 現行 WiFi、Network、FS、USB ライブラリ | Arduino 側の内部依存を追って追加移植する必要がある |

Arduino API、プロトコルスタック、controller driver、PHY、FreeRTOS、heap 等の基盤は、別々の選択肢として扱う。Arduino API だけを実装すれば下位基盤まで不要になるという意味ではないが、現行の Arduino ESP32 wrapper やスタック全体を再現する必要もない。個別ライブラリの無変更移植を、独自コアの成立条件には置かない。[スタックと下位基盤の選択](build-cost-analysis.ja.md)

**期待できる効果**: 初回ビルドの対象と公開ヘッダーの大幅な整理、不要な Arduino 初期化依存の削減。**残る制約**: SDK が強制的に入れる runtime・初期化と SDK 側の既定設定。IDF 依存を減らす前に、この境界だけを軽くする価値は大きい。

## 案4 lib-builder の設定を変えて以降を独自にする

**実現性は高いが、目的別 SDK とコアを一体で管理する必要がある。**

上流のビルド・抽出処理を維持して、sdkconfig、コンポーネント選択、対象チップ・メモリ構成を絞る。公式にも設定変更用の lib-builder が提供されている。[Library Builder](https://docs.espressif.com/projects/arduino-esp32/en/latest/lib_builder.html)

ローカルの `defconfig.common` は C++ 例外を有効にし、FreeRTOS の統計、広い lwIP 機能、複数の TLS 機能等を選んでいる。`main/idf_component.yml` にはチップ条件付きで camera、TFLite、音声認識、Matter、video 等がある。これらを用途別に整理する。

| 見直すもの | 主な効果と条件 |
| --- | --- |
| 不要な追加コンポーネント | SDK 生成・取得・配布量、公開 include、リンク入力を減らしやすい |
| 診断、core dump、ログ、trace | 強制初期化、常駐データ、Flash を減らす候補 |
| C++ 例外や RTTI | 利用するコードの要件に合わせる。今回 RTTI は既に無効 |
| lwIP と TLS の機能・バッファ | 対応機能と RAM の交換。通常のビルド時間への効果は別途測る |
| Wi-Fi・Bluetooth・USB 等 | 使わない構成では候補。既存ライブラリが前提にしていないか確認 |
| 対象 SoC、flash、PSRAM の組み合わせ | SDK 生成回数と配布量を減らす。通常の1アプリのコンパイル量とは別 |

Kconfig だけでなく、manifest と `REQUIRES` による依存を除く必要がある。ある機能を無効にしても、別の component が要求すればビルド対象に入る。逆に、`.a` から `.o` を手で削る方法では、必要な初期化や設定の整合性を維持しにくい。

運用は、最小用途、ネットワーク用途、USB用途など少数の固定 profile にする。すべての機能のオンオフを組み合わせると、SDK の生成・配布・検証対象が膨らむ。

重要なのは、スケッチで `#define CONFIG_...` を変えても、既にビルド済みの IDF `.a` の実装や構造体レイアウトは変わらないこと。設定を変えた SDK は、ヘッダー・flags・linker script・必要な bootloader と一緒に生成・配布する。

なお今回の recipe は `compiler.cpp.extra_flags` の後に SDK の `cpp_flags` を置く。前に `-fno-exceptions` を追加しても、response file 内の後の `-fexceptions` が優先される場合がある。フラグの設定名だけでなく、展開後のコマンドを確認する。

**限界**: 大きな SDK の `.a` が小さくなっても、通常のビルドでは元から再コンパイルしていない。体感速度は主に include、リンク、参照関係が変わる部分から得る。無線・TLS・USB 等を削ったこと自体を高速化の保証にはしない。

## 案5 lib-builder 相当から独自に作る

**技術的には十分可能。ただし「SDK を作る仕組みの変更」と「SDK の中身を軽くする変更」は別である。**

最も現実的なのは、ESP-IDF の標準 CMake を使う小さな SDK 生成プロジェクトと、生成物のエクスポーターを作ること。lib-builder の全機能、対象チップ、追加コンポーネントを再現する必要はない。

独自の責任になるものは、component の依存解決、Kconfig、ヘッダーと生成ヘッダーの収集、archive の収集、linker script と配置規則、compile/link flags、bootloader・partition・flash/PSRAM 構成、toolchain 固定、配布 manifest、更新時の検証である。

IDF の CMake API は外部の CMake から component をビルドする用途にも使える。生成依存をその API から取り、`build.ninja` の文字列を場当たり的に解析する仕組みを増やさない方が保守しやすい。[ESP-IDF 5.5 Build System](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-guides/build-system.html)

二つの配布方式が考えられる。

| 方式 | 特徴 |
| --- | --- |
| 用途別 SDK を事前生成して配布 | Arduino の反復ビルドを軽くしやすい。SDK 更新時に生成・検証費用をまとめて負担 |
| アプリごとに IDF component としてビルド | 設定を細かく選べ、Ninja の増分処理を利用できる。一方、初回に IDF をビルドする費用が入る |

SDK を外部で事前生成する場合、最終アプリのリンク情報、設定、bootloader の関係を manifest に固定する。プロジェクトごとに IDF をソースビルドする方式に変えるなら、いま省けている費用を初回へ戻す点を評価する。

ローカルの lib-builder には、同じチップと設定なら build を再利用する仕組みが既にある。2026年11月13日の `c26041d` で再利用性の修正も入っている。独自化の前に、その仕組みで十分かを比較できる。ただしこれは SDK を作る工程の改善であり、通常の Arduino スケッチの core.a キャッシュとは別である。[build.sh の固定版](https://github.com/espressif/esp32-arduino-lib-builder/blob/c26041da7e672c6984babbd76de855474283631c/build.sh)

**採用条件**: 案4では削れない Arduino 向け前提が邪魔、少数チップに固定した再現可能な SDK 配布が必要、またはエクスポート方式そのものを管理したい場合。ビルド待ちだけが問題なら、まず他の小さな変更で解決する方が早い。

## 案6 ESP-IDF 依存を最小にして独自に作る

この案は一段階ではない。依存には、ソースの include、リンクする関数、実行時のシステム基盤、ビルドツール、配布バイナリという別の意味がある。

### 公開 API から IDF を隠す

**実現性は高い。** 内部では IDF を十分使いながら、ユーザー向けには小さな宣言だけを公開する。案3と両立する。ヘッダー解析と変更の波及を抑えられ、既存の無線や FreeRTOS を維持しやすい。依存を減らす第一歩として最も扱いやすい。

### 必要な IDF component だけにする

**実現性は高い。** startup、FreeRTOS、heap、timer、必要な driver を残し、network・storage・診断等は用途に応じて追加する。IDF 5.5 では `COMPONENTS`、または `MINIMAL_BUILD` が使える。ただし依存先は再帰的に追加され、共通 component も残る。空の IDF や RTOS なしになる設定ではない。[IDF の component 選択](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-guides/build-system.html#component-requirements)

公式 Arduino component のままでは、`CORE_SRCS` が広く、`REQUIRES` / `PRIV_REQUIRES` も広い。最小化するなら、その境界を分ける必要がある。

### 周辺だけを直接実装する

**1チップの GPIO・UART 等から始めれば実現性は高い。** IDF の startup と FreeRTOS は使い、単純な周辺 API を HAL/LL や直接レジスターで実装する。これは IDF 全廃と、既存 driver をそのまま使う案の中間にある。

ただし GPIO のクロック、pin matrix、割り込み、DMA、cache coherency、電力管理、flash 書き込み中の IRAM 安全性などを管理する必要がある。Wi-Fi が周波数や省電力を管理する構成では、独立した register 操作が衝突する可能性もある。特に ISR は関数だけでなく、呼び出し先と読み出す定数の配置も関係する。[ESP-IDF Memory Types](https://docs.espressif.com/projects/esp-idf/en/v5.5.1/esp32/api-guides/memory-types.html)

チップ固有部分は backend に隔離し、最初から全 ESP32 系列を直接実装しない。たとえば S3 の USB・cache・PSRAM を扱う負担と、C3 の単純な GPIO を扱う負担は同じではない。

### FreeRTOS と startup まで置き換える

**周辺用途に絞れば実現可能だが、工数と保守費用は大きい。** reset entry、stack、`.data` / `.bss`、C++ 初期化、例外ベクター、割り込み、flash mapping、cache、ROM 関数、heap、時刻、watchdog、マルチコア等を選択的に実装する必要がある。

通常の IDF driver を、FreeRTOS と IDF runtime がないまま同じ `.a` で使えるとは限らない。IDF 依存を runtime まで切る地点で、「同じ SDK の使い回し」という前提も見直すことになる。

bare metal の実現例として Espressif の Rust エコシステムには `esp-hal` がある。ESP32 が IDF runtime なしでは動かせないという意味ではない。ただし Rust の backend を、C++ の Arduino コアにそのまま置換できることを示すものではない。[esp-hal](https://github.com/esp-rs/esp-hal)

### 無線を残して IDF runtime を置き換える

**可能性はあるが、最も慎重に切り分けるべき領域。** IDF の Wi-Fi component は `net80211`、`pp` 等の prebuilt library を使い、event、PHY、netif、timer、NVS、coexistence 等とも依存する。単に `libesp_wifi.a` をコピーしてリンクすれば済む構造ではない。[ESP-IDF Wi-Fi CMake](https://github.com/espressif/esp-idf/blob/v5.5/components/esp_wifi/CMakeLists.txt)

`esp-wifi-sys` は bare metal の無線実装へドライバーを組み込む先行例である。したがって「無線には IDF の全 runtime が必須」と断定する必要はないが、OS 接続、メモリ、時間、割り込み、排他、PHY・無線の設定の整合性が必要になる。[esp-wifi-sys](https://github.com/esp-rs/esp-wifi-sys)

TinyEsp32 で無線と多数の既存 IDF 利用ライブラリを必要とするなら、まず公開依存と component を減らし、IDF の基盤を残す方が実用的。無線不要の小さなデバイス用途は、別 backend として bare metal を検討できる。

## 当初の6案の間にある独立した選択肢

### コアを事前コンパイルして配る

コアを軽く書き直す前に、**いまのコア自体を事前に core.a にする**案がある。互換性を保ちつつ、新しいスケッチの初回負担を減らせる。標準共有キャッシュはその場で生成した core.a の再利用であり、ここでいう配布時の事前生成とは分ける。

Arduino の `precompiled=full` はライブラリの仕組みで、既存コアにその一行を追加すれば有効になるものではない。独自 platform なら、薄いコア用ソースと公開ヘッダー、事前生成 archive を link recipe で組み合わせられる。[Arduino library specification](https://docs.arduino.cc/arduino-cli/library-specification/)

CPU、ボード variant、USB、PSRAM、loop core、DebugLevel、独自マクロ等がコアのコンパイル結果に影響する。その組み合わせを無制限に事前生成せず、安定した ABI の部分を先にコンパイルし、ボード設定を小さな `.cpp` や定数テーブルに分ける設計がよい。

### Arduino CLI の前処理だけを外す

アプリ本体を `.cpp` と明示した依存一覧にし、CMake/Ninja 等で既存 SDK・core.a にリンクする。SDK とコアを変えず、`.ino` の自動 prototype 生成や繰り返しの探索を避ける中間案である。Arduino CLI は書き込み等に使い続ける構成も考えられる。

Arduino CLI の通常のビルドを、IDE 上でそのまま完全な Ninja の依存グラフに変える設定ではない。include・define・recipe・partition の正確な引き継ぎとライブラリ選択は独自ビルド側の責任になる。

### Arduino を ESP-IDF component として使う

公式に用意された経路で、現行 Arduino API を残して CMake/Ninja と設定管理を利用できる。反復開発で、変更がないリンクや生成処理まで依存グラフで省ける可能性がある。[Arduino as an ESP-IDF component](https://docs.espressif.com/projects/arduino-esp32/en/latest/esp-idf_component.html)

ただし初回は IDF もソースビルドすることになり、現在の prebuilt SDK に比べて重くなる場合がある。独立した多数のプロジェクト間で IDF のオブジェクトが自動共有されるわけでもない。長く育てる一つのアプリには向きやすく、短いスケッチを大量に切り替える用途では別途キャッシュが要る。

### 公式の選択コンパイルを利用する

3.3.13 の Arduino component には `CONFIG_ARDUINO_SELECTIVE_COMPILATION` と、ライブラリごとの `CONFIG_ARDUINO_SELECTIVE_*` が存在する。独自フォーク前に利用できる余地がある。[Arduino CMakeLists.txt](https://github.com/espressif/arduino-esp32/blob/3.3.13/CMakeLists.txt)、[Kconfig.projbuild](https://github.com/espressif/arduino-esp32/blob/3.3.13/Kconfig.projbuild)

ただし選択対象は主に `ARDUINO_ALL_LIBRARIES` 側で、`CORE_SRCS` は別に列挙されている。Arduino CLI のコア列挙を、この設定だけで「使用したコアファイルだけ」に変えられるわけではない。通常の Arduino CLI はスケッチから発見したライブラリを対象にするため、component モードの既定の全ライブラリ処理と混同しない。

### PCH と翻訳単位の整理

PCH は、共通の重いヘッダーをコンパイル済みの形で再利用する方法。IDF や API を作り替えず、繰り返すヘッダー解析を減らせる。ただし compiler 本体、言語、target、関係するマクロ・オプションが一致する必要がある。ボード・USB・PSRAM 等の設定で PCH を分け、`-H` や `-Winvalid-pch` 等で実際に利用されたか確認する。[GCC Precompiled Headers](https://gcc.gnu.org/onlinedocs/gcc/Precompiled-Headers.html)

PCH は設定が安定している場合に有望。公開ヘッダーを変えたときの再生成費用も含めて評価する。全ヘッダーを一つの PCH に押し込むと変更の波及は広がる。

複数ソースをまとめる unity build も include 回数を減らせるが、`static` 名やマクロの衝突、変更時の大きな再コンパイル、archive の取り出し単位の粗大化が起きうる。小さく独立した部分に限定する。ヘッダー専用化も含め、ソース本数の削減と増分性の交換になる。

### C++ と標準ライブラリの方針を変える

公開 API の `<functional>`、テンプレートの量、例外、String・Stream の実装を小さくする余地はある。ビルド時間とコードサイズの両方に影響するが、API 互換と ABI に関わるため、単なる最適化フラグ変更より広い設計判断である。

CH32 側の LLVM/Clang・picolibc・libc++ の構成を、既存 ESP32 SDK にそのまま持ち込めるとは限らない。特に Xtensa の対応、Espressif の GCC 前提、配布済み `.a` と C/C++ runtime の整合性がある。最初は現在の toolchain を維持し、公開ヘッダーと到達性を改善する方が変数を減らせる。

`-g0` 等でデバッグ情報を減らす案は、`.o` / ELF の生成や I/O を減らす候補だが、Flash のコードが同じだけ減るわけではない。LTO、最適化レベル、例外無効化も、それぞれビルド時間と機能・サイズの交換として別々に測る。

## 比較する軸

下表の効果は、測定値があるキャッシュを除いて構造からの見通し。高・中・低は相対評価で、速度倍率や工数日数を意味しない。

| 選択肢 | 初回ビルド | スケッチ変更 | Flash と RAM | 既存互換 | 保守負担 |
| --- | --- | --- | --- | --- | --- |
| キャッシュと安定した呼び出し | 共有 hit 時に大 | 大。ただしリンク等は残る | 原則不変 | 高 | 低 |
| ccache | miss 時は不変 | 条件が合う再コンパイルに有効 | 原則不変 | 高 | 低〜中 |
| 出力処理とビルドグラフの整理 | 小〜中 | 有望 | 原則不変 | 高 | 中 |
| コアの事前配布 | 大 | コア再生成時にも有効 | 原則不変 | 高 | 設定数によって中〜高 |
| PCH と薄い公開ヘッダー | 中 | 有望 | PCH 自体は原則不変 | 中〜高 | 中 |
| 小規模なコアフォーク | 削る範囲次第 | 変更対象次第 | 到達性の削減に有効 | 中〜高 | 中 |
| 同じ SDK 上の独自コア | 大を狙える | 公開 API 次第で有望 | Arduino 側の基礎費用を削減 | 段階的 | 高 |
| lib-builder の用途別設定 | 通常アプリでは限定的 | include とリンク次第 | SDK 側も削減可能 | 用途内で維持 | 中〜高 |
| 独自 SDK 生成工程 | 設計次第 | 設計次第 | 構成を変えた分だけ | 管理した範囲内 | 高 |
| IDF の必要 component と直接 driver | 大を狙える | 有望 | 基盤まで削減可能 | 移植が必要 | 高 |
| bare metal と独自 runtime | 小さくできる | 小さくできる | 最小化の自由度が高い | 低 | 非常に高 |

案番号が大きいほど必ず速くなるわけではない。たとえば案5で毎プロジェクト IDF をソースビルドする方式に変えると、案1の prebuilt SDK とキャッシュより初回が遅くなることがある。

### 現行環境を対照として測る

実際に遅いプロジェクトの FQBN、profile、CLI コマンド、build-path、ログを固定し、今回の最小スケッチと同じ条件表を作る。次に同じ build-path の再利用または標準共有キャッシュを採用する。開発機と CI の並列数も分けて評価する。

対照構成では、スケッチの一行変更でコアの実コンパイルがゼロになることを確認する。待ち時間だけが目的ならこの変更で足りる場合があるが、SDK の設定自由度を戻す目的があれば別の比較も必要になる。

### 互換性を保つ小さな変更を比較する

起動診断のコンパイル時除外、入力が変わらない bootloader の再利用、不要な merged bin 生成の後回し、公開ヘッダーの限定を個別に試す。次に ccache・PCH・事前生成 core.a を比較する。変更を同時に入れず、それぞれがどの工程を減らしたかを見る。

合格条件は、同じアプリの機能を保って待ち時間が減ること。Flash・RAM・debug 情報の差も別に記録する。

### Arduino API を保つ独自コアを比較する

最初は1チップと少数ボードに固定する。GPIO、時間、Serial、Print/Stream、割り込みから始め、SPI・Wireを追加する。既存の Arduino コアと同じ SDK を使って、上位コアの設計差だけを比較する。

この段階で最小ヘッダーの効果、不要な初期化依存、必要時に取り出せるモジュールの境界が見える。無線や USB はそれぞれを必要とする実アプリを一つ選んで移植し、汎用 API だけで十分かを確認する。

### SDK の最小化と設定自由度を比較する

削るべき IDF 機能と、アプリが変更したい設定を列挙する。固定 SDK の種類を増やす案、変更の必要な component をソースで供給する案、実行時設定へ変える案を比較する。上流の抽出方式が障害になるなら案5を検討し、runtime の置換が目的に合うなら案6も比較する。現在の層をすべて順に改造することを採用順として決めてはいない。

## 比較実験で確認する項目

| 実験 | 主に確認すること |
| --- | --- |
| 空の build から開始 | core・library の実コンパイル数、SDK 取得時間 |
| 同じ入力で再実行 | キャッシュ利用、リンク・イメージ生成の有無 |
| スケッチの定数だけ変更 | 解析とコンパイルの反復費用 |
| 公開ヘッダー変更 | 再ビルドの波及範囲 |
| 内部の実装だけ変更 | 必要な翻訳単位だけに閉じるか |
| ボード設定を変えて戻す | 正しいキャッシュの分離と再利用 |
| 最小、Serial、SPI/Wire、Wi-Fi/TLS、USB の各アプリ | 削減効果が用途ごとに逆転しないか |

実機では、起動・reset・時間精度・割り込み・watchdog・周辺の再割り当てを確認する。該当機能を使う構成では、マルチコア、PSRAM、flash 書き込み中の ISR、USB、無線、OTA も確認する。RAM は ELF の静的領域だけでなく、起動後と機能開始後の heap・task stack を測る。

時間は同条件で繰り返し、中央値とばらつきを残す。キャッシュの cold は「ビルド成果物がない」の意味とし、OS のページキャッシュまで空にした測定とは区別する。別の処理が動く開発機での値を、専用機で得た厳密な性能値として扱わない。

## 再現方法と保存した根拠

測定用コードと記録は [research/2026-11-22](research/2026-11-22/) に保存した。`measure.py`、`inspect.py`、`debug_report_probe.py` は今回使ったスクリプトである。前者が作るログを後二つが使用する。

SDK とツールの取得が必要になる環境では、それを先に済ませて計測する。以下は一時領域に測定用ファイルを作る例で、ボードへの書き込みはしない。実行元は TinyEsp32 のルートを想定する。

```bash
survey_dir=$(mktemp -d /tmp/tinyesp32-survey-XXXXXX)
cp docs/research/2026-11-22/measure.py "$survey_dir/"
cp docs/research/2026-11-22/inspect.py "$survey_dir/"
cp docs/research/2026-11-22/debug_report_probe.py "$survey_dir/"
mkdir "$survey_dir/Minimal"
cp docs/research/2026-11-22/Minimal.ino "$survey_dir/Minimal/"
cp docs/research/2026-11-22/sketch.yaml "$survey_dir/Minimal/"
python3 "$survey_dir/measure.py"
python3 "$survey_dir/inspect.py"
python3 "$survey_dir/debug_report_probe.py"
```

`measure.py` の既定パスの初回ビルドは、既存の共有キャッシュがあれば hit になる。今回の測定でも共有キャッシュは削除しておらず、結果としてそのキーが miss した。`inspect.py` と probe は今回の Xtensa S3 向けログを使う探索用スクリプトで、任意の SoC に対応する汎用ツールではない。

保存した資料は次のとおり。

- [build-measurements.json](research/2026-11-22/build-measurements.json): 実行条件、壁時計時間、実コンパイル数、工程の出力時刻。
- [header-link-measurements.json](research/2026-11-22/header-link-measurements.json): ヘッダー量と各3回の探索的計測。
- [debug-report-probe.json](research/2026-11-22/debug-report-probe.json): 同じ SDK での診断関数差し替えと bin サイズ。
- [inventory.json](research/2026-11-22/inventory.json): 解決された版、SDK の生成時の版情報、調査したソースのハッシュ。
- [build-log-excerpts.txt](research/2026-11-22/build-log-excerpts.txt): コア再利用、生成処理、使用量を示すログ抜粋。

今回変更したのは TinyEsp32 の文書と調査用スクリプトだけである。既存の ESP32 / CH32 コアや SDK は変更していない。独自コア・用途別 SDK・bare metal の各案は、上記のソース境界から実現性を評価したもので、移植済み・実機検証済みの実装を意味しない。
