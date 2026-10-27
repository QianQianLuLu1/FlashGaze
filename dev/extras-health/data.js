window.BENCHMARK_DATA = {
  "lastUpdate": 1793142600565,
  "repoUrl": "https://github.com/QianQianLuLu1/FlashGaze",
  "entries": {
    "FlashGaze Extras Coverage": [
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "2d94e0889331cf1715919ad89287094276e9f175",
          "message": "docs(ci): 用第三轮实测把单点值改成区间，并记下「拿单样本当结论」这笔账\n\n第三个终验 run 40189037679 也是 success（21 个 job、0 失败，两个 macos extras 产物照样生成）。\n但它把上一版文档里的两处说法打破了：\n\n1. macOS 测试步不是 380/375s 两值，第三轮是 505s；job 全程 661 / 681 / 882s。同一轮 install\n   也从 252s 跳到 349s——同一条腿跨运行波动约 ±35%。上一版据此写的「变成 ~377s 完成」是拿单\n   样本当结论，现改为只报**完成性与区间**：三轮全部跑完、最差 882s = 14.7 分钟。\n2. 由此 headroom 也从「~3.6 倍」下调为「最差一轮仍 ≥2.7 倍」；「真实需求 ~11 分钟」改为「≤15 分钟」。\n   结论方向不变：40 仍是余量天花板，不是实测需求，也不下调。\n\n顺带把倍率按三轮逐一对齐后写成 0.98~1.31 倍（380/302、375/382、505/384），与默认矩阵 1.46 倍\n同带；ubuntu 三轮 302/382/384s 与修复前 306/404s 同区间，无可测变化——ProcessPoolExecutor 未\n指定 mp_context，Linux 默认 fork、worker 不重新导入本模块，所以「ubuntu 不变」本身就是根因\n成立的旁证，而不是遗漏。\n\n教训写进 pitfalls §3.13 与 fixes §4.11：凡按单轮 step 时序下结论，先问「这是几轮采样」。本轮\n我在同一个数字上栽了两次（先是照 58% 停点线性外推 31 分钟，再是拿一轮 380s 当点值），两笔都\n如实记账，不删不改前次表述。\n\n纯文案与注释，无行为改动：ruff / format / mypy 两面 / check_agents_md 全绿，\n契约 18 + 预算 4 + extras-health 规则 7 = 29 条通过。",
          "timestamp": "2026-10-25T11:59:05Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/2d94e0889331cf1715919ad89287094276e9f175"
        },
        "date": 1792965382973,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "flashgaze.mcp_server",
            "value": 87.71,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-25T21:56:11.127343+00:00"
          },
          {
            "name": "flashgaze.webui.app",
            "value": 85.77,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-25T21:56:11.127343+00:00"
          },
          {
            "name": "flashgaze.core.xlsx_exporter",
            "value": 100,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-25T21:56:11.127343+00:00"
          },
          {
            "name": "flashgaze.core.deduplicator",
            "value": 83.72,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-25T21:56:11.127343+00:00"
          },
          {
            "name": "flashgaze.core.portrait_engine",
            "value": 51.11,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-25T21:56:11.127343+00:00"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "2d94e0889331cf1715919ad89287094276e9f175",
          "message": "docs(ci): 用第三轮实测把单点值改成区间，并记下「拿单样本当结论」这笔账\n\n第三个终验 run 40189037679 也是 success（21 个 job、0 失败，两个 macos extras 产物照样生成）。\n但它把上一版文档里的两处说法打破了：\n\n1. macOS 测试步不是 380/375s 两值，第三轮是 505s；job 全程 661 / 681 / 882s。同一轮 install\n   也从 252s 跳到 349s——同一条腿跨运行波动约 ±35%。上一版据此写的「变成 ~377s 完成」是拿单\n   样本当结论，现改为只报**完成性与区间**：三轮全部跑完、最差 882s = 14.7 分钟。\n2. 由此 headroom 也从「~3.6 倍」下调为「最差一轮仍 ≥2.7 倍」；「真实需求 ~11 分钟」改为「≤15 分钟」。\n   结论方向不变：40 仍是余量天花板，不是实测需求，也不下调。\n\n顺带把倍率按三轮逐一对齐后写成 0.98~1.31 倍（380/302、375/382、505/384），与默认矩阵 1.46 倍\n同带；ubuntu 三轮 302/382/384s 与修复前 306/404s 同区间，无可测变化——ProcessPoolExecutor 未\n指定 mp_context，Linux 默认 fork、worker 不重新导入本模块，所以「ubuntu 不变」本身就是根因\n成立的旁证，而不是遗漏。\n\n教训写进 pitfalls §3.13 与 fixes §4.11：凡按单轮 step 时序下结论，先问「这是几轮采样」。本轮\n我在同一个数字上栽了两次（先是照 58% 停点线性外推 31 分钟，再是拿一轮 380s 当点值），两笔都\n如实记账，不删不改前次表述。\n\n纯文案与注释，无行为改动：ruff / format / mypy 两面 / check_agents_md 全绿，\n契约 18 + 预算 4 + extras-health 规则 7 = 29 条通过。",
          "timestamp": "2026-10-25T11:59:05Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/2d94e0889331cf1715919ad89287094276e9f175"
        },
        "date": 1793031435441,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "flashgaze.mcp_server",
            "value": 87.71,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-26T16:17:04.218904+00:00"
          },
          {
            "name": "flashgaze.webui.app",
            "value": 85.77,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-26T16:17:04.218904+00:00"
          },
          {
            "name": "flashgaze.core.xlsx_exporter",
            "value": 100,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-26T16:17:04.218904+00:00"
          },
          {
            "name": "flashgaze.core.deduplicator",
            "value": 83.72,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-26T16:17:04.218904+00:00"
          },
          {
            "name": "flashgaze.core.portrait_engine",
            "value": 51.11,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-26T16:17:04.218904+00:00"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "2d94e0889331cf1715919ad89287094276e9f175",
          "message": "docs(ci): 用第三轮实测把单点值改成区间，并记下「拿单样本当结论」这笔账\n\n第三个终验 run 40189037679 也是 success（21 个 job、0 失败，两个 macos extras 产物照样生成）。\n但它把上一版文档里的两处说法打破了：\n\n1. macOS 测试步不是 380/375s 两值，第三轮是 505s；job 全程 661 / 681 / 882s。同一轮 install\n   也从 252s 跳到 349s——同一条腿跨运行波动约 ±35%。上一版据此写的「变成 ~377s 完成」是拿单\n   样本当结论，现改为只报**完成性与区间**：三轮全部跑完、最差 882s = 14.7 分钟。\n2. 由此 headroom 也从「~3.6 倍」下调为「最差一轮仍 ≥2.7 倍」；「真实需求 ~11 分钟」改为「≤15 分钟」。\n   结论方向不变：40 仍是余量天花板，不是实测需求，也不下调。\n\n顺带把倍率按三轮逐一对齐后写成 0.98~1.31 倍（380/302、375/382、505/384），与默认矩阵 1.46 倍\n同带；ubuntu 三轮 302/382/384s 与修复前 306/404s 同区间，无可测变化——ProcessPoolExecutor 未\n指定 mp_context，Linux 默认 fork、worker 不重新导入本模块，所以「ubuntu 不变」本身就是根因\n成立的旁证，而不是遗漏。\n\n教训写进 pitfalls §3.13 与 fixes §4.11：凡按单轮 step 时序下结论，先问「这是几轮采样」。本轮\n我在同一个数字上栽了两次（先是照 58% 停点线性外推 31 分钟，再是拿一轮 380s 当点值），两笔都\n如实记账，不删不改前次表述。\n\n纯文案与注释，无行为改动：ruff / format / mypy 两面 / check_agents_md 全绿，\n契约 18 + 预算 4 + extras-health 规则 7 = 29 条通过。",
          "timestamp": "2026-10-25T11:59:05Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/2d94e0889331cf1715919ad89287094276e9f175"
        },
        "date": 1793056600664,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "flashgaze.mcp_server",
            "value": 87.71,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-26T23:16:30.660324+00:00"
          },
          {
            "name": "flashgaze.webui.app",
            "value": 85.77,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-26T23:16:30.660324+00:00"
          },
          {
            "name": "flashgaze.core.xlsx_exporter",
            "value": 100,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-26T23:16:30.660324+00:00"
          },
          {
            "name": "flashgaze.core.deduplicator",
            "value": 83.72,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-26T23:16:30.660324+00:00"
          },
          {
            "name": "flashgaze.core.portrait_engine",
            "value": 51.11,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-26T23:16:30.660324+00:00"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "2d94e0889331cf1715919ad89287094276e9f175",
          "message": "docs(ci): 用第三轮实测把单点值改成区间，并记下「拿单样本当结论」这笔账\n\n第三个终验 run 40189037679 也是 success（21 个 job、0 失败，两个 macos extras 产物照样生成）。\n但它把上一版文档里的两处说法打破了：\n\n1. macOS 测试步不是 380/375s 两值，第三轮是 505s；job 全程 661 / 681 / 882s。同一轮 install\n   也从 252s 跳到 349s——同一条腿跨运行波动约 ±35%。上一版据此写的「变成 ~377s 完成」是拿单\n   样本当结论，现改为只报**完成性与区间**：三轮全部跑完、最差 882s = 14.7 分钟。\n2. 由此 headroom 也从「~3.6 倍」下调为「最差一轮仍 ≥2.7 倍」；「真实需求 ~11 分钟」改为「≤15 分钟」。\n   结论方向不变：40 仍是余量天花板，不是实测需求，也不下调。\n\n顺带把倍率按三轮逐一对齐后写成 0.98~1.31 倍（380/302、375/382、505/384），与默认矩阵 1.46 倍\n同带；ubuntu 三轮 302/382/384s 与修复前 306/404s 同区间，无可测变化——ProcessPoolExecutor 未\n指定 mp_context，Linux 默认 fork、worker 不重新导入本模块，所以「ubuntu 不变」本身就是根因\n成立的旁证，而不是遗漏。\n\n教训写进 pitfalls §3.13 与 fixes §4.11：凡按单轮 step 时序下结论，先问「这是几轮采样」。本轮\n我在同一个数字上栽了两次（先是照 58% 停点线性外推 31 分钟，再是拿一轮 380s 当点值），两笔都\n如实记账，不删不改前次表述。\n\n纯文案与注释，无行为改动：ruff / format / mypy 两面 / check_agents_md 全绿，\n契约 18 + 预算 4 + extras-health 规则 7 = 29 条通过。",
          "timestamp": "2026-10-25T11:59:05Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/2d94e0889331cf1715919ad89287094276e9f175"
        },
        "date": 1793142599473,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "flashgaze.mcp_server",
            "value": 87.71,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-27T23:09:42.584331+00:00"
          },
          {
            "name": "flashgaze.webui.app",
            "value": 85.77,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-27T23:09:42.584331+00:00"
          },
          {
            "name": "flashgaze.core.xlsx_exporter",
            "value": 100,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-27T23:09:42.584331+00:00"
          },
          {
            "name": "flashgaze.core.deduplicator",
            "value": 83.72,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-27T23:09:42.584331+00:00"
          },
          {
            "name": "flashgaze.core.portrait_engine",
            "value": 51.11,
            "range": "RANGE",
            "unit": "%",
            "extra": "2026-10-27T23:09:42.584331+00:00"
          }
        ]
      }
    ]
  }
}