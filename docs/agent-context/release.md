# FlashGaze 发布流程语义

> 本文件从 `AGENTS.md` §8 拆分而来，承载完整的发布流程细节。
> AGENTS.md 保留摘要与导航链接。

---

- **唯一真实发布路径**：推送版本标签 `git tag vx.y.z && git push origin vx.y.z`
- **手动触发（workflow_dispatch）**：恒为演练——构建 + 验证 + 证明生成，**不发布**
- **发布认证**：PyPI Trusted Publishing（OIDC），无需仓库 Secret
  - **首次发布前需人工登记的 Trusted Publisher 三要素**：Owner `<repo owner>` / Repository `<repo name>` / **Workflow name `release.yml`**。
    Workflow name 填的是**文件名且必须带 `.yml`**（GitHub 官方 PyPI-OIDC 文档示例即 `release.yml`）；`.github/workflows/release.yml` 声明的显示名是 `name: Release`，PyPI **不比对显示名**，填成 `release` 或 `Release` 都会让 `publish` job 以 trusted-publisher 不匹配失败。Environment 留空。
- **供应链证明**：SLSA Build Provenance + CycloneDX SBOM（Sigstore 签名）
- **版本源**：`flashgaze/__init__.py::__version__`（标签必须与之一致，preflight 校验）
- **失败行为**：
  - preflight / build / verify / attest 失败 → 尚未发布，无副作用
  - publish 失败 → 下游 Release 不创建，重跑整个工作流
  - github-release 失败 → PyPI 已发布，单独重跑 github-release job（幂等）
