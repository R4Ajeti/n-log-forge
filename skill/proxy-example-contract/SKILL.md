---
name: proxy-example-contract
description: Create or maintain raw request, input, and output examples when implementing or changing an external-system proxy or adapter.
---

# Proxy Example Contract

A new proxy is complete only when it includes at least one safe, matching usage example. Update existing examples whenever its input, request, or response contract changes.

## Required artifacts

Use the repository's raw-example location; default to `raw/proxy/<proxy_name>/` relative to the project root. Derive `<proxy_name>` from the implementation's existing naming convention. Keep these filenames together:

```text
<proxy_name>/
  request.txt
  json/
    input.json
    output.json
```

- **`request.txt`**: Describe the operation, target, protocol, and relevant parameters. For HTTP, include the URL, method, and required headers. For an SDK, queue, RPC, or other transport, document its actual invocation instead. Explain authentication placeholders, prerequisites, and material side effects.
- **`json/input.json`**: Provide valid JSON representing realistic input accepted by the proxy. Distinguish proxy arguments from the external request body when they differ.
- **`json/output.json`**: Provide valid JSON matching the result returned by the proxy. Explain any difference from the provider's raw response in `request.txt`.

Keep all three files for operations without JSON payloads. For an absent input or result, use JSON `null` and explain its meaning. For non-JSON data, use a clearly labeled JSON fixture descriptor containing safe example text, encoded content, or a relative fixture-file reference, plus the actual media type/encoding. Explain how it maps to the real input/result in `request.txt`; do not present a descriptor as the wire format or invent a JSON response shape. Add a separate fixture only when needed to represent the contract accurately.

## Safety and validation

Use synthetic, representative data and obvious authentication placeholders. Exclude credentials, tokens, API keys, passwords, private IPs/endpoints, and sensitive provider or production data.

Verify that the three required files exist, both JSON files parse, referenced fixtures resolve, and the example matches the implemented proxy's current behavior. Check transformations as well as field names and types. Clearly distinguish illustrative samples from recorded or executed results; validation does not require a live provider call.
