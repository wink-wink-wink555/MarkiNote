# Security Policy / 安全策略

## Supported versions / 支持版本

| Version | Security support |
|---|---|
| `main` / 4.x | Supported / 支持 |
| `lite` legacy branch | Archived; no regular security fixes / 归档，不承诺常规安全修复 |
| Earlier versions | Not supported / 不支持 |

Until the first immutable 4.x release is published, `main` is the only supported source line. Production deployments should use a reviewed release tag and the paired API/gateway image digests produced by the release workflow.

在首个不可变的 4.x 正式版本发布前，只有 `main` 属于受支持代码线。生产部署应使用已审查的 Release tag，以及同一次发布工作流生成的 API/gateway 镜像 digest。

## Reporting a vulnerability / 报告漏洞

Please do not disclose exploitable details in a public issue, discussion, log, screenshot, or sample document.

请勿在公开 Issue、Discussion、日志、截图或示例文档中披露可利用细节。

1. Use GitHub's **Report a vulnerability** action on this repository's Security page to open a private report.
2. Include the affected version or commit, deployment profile, impact, minimal reproduction, and any suggested mitigation.
3. Remove access tokens, AI provider keys, document contents, local paths, and personal data from all evidence.
4. If private vulnerability reporting is unavailable, open a minimal public issue requesting a private contact channel. Do not include the vulnerability details or proof of concept.

1. 优先在本仓库的 Security 页面使用 **Report a vulnerability** 提交私密报告。
2. 请说明受影响版本或 commit、部署档位、影响、最小复现与可选缓解建议。
3. 所有证据必须移除访问令牌、AI 服务密钥、文档正文、本地路径与个人信息。
4. 如果私密漏洞报告尚未启用，请只创建一个请求私密沟通渠道的最小公开 Issue，不要附漏洞细节或利用代码。

The maintainer will make a best effort to acknowledge a private report within seven days, validate impact, coordinate a fix, and agree on a disclosure timeline. This is a best-effort open-source response target, not a service-level agreement.

维护者会尽力在七天内确认私密报告，随后验证影响、协调修复并约定披露时间；这是开源项目的尽力响应目标，不构成服务等级承诺。

## Security-sensitive areas / 重点范围

Reports are especially useful for authentication bypass, path traversal or symlink escape, stored/reflected XSS, SSRF or redirect/DNS rebinding, secret leakage, unsafe document mutation or rollback, cross-conversation authorization errors, and container/deployment boundary failures.

重点关注：认证绕过、路径穿越或符号链接逃逸、存储型/反射型 XSS、SSRF 或重定向/DNS rebinding、秘密泄漏、不安全的文档修改或回滚、跨会话授权错误，以及容器/部署边界失效。
