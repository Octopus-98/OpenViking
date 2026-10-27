//! Verify attrs options and key selection through the real CLI and HTTP request.
use serde_json::{Value, json};
use std::{fs, process::Stdio, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    process::Command,
    time::timeout,
};

#[tokio::test]
async fn attrs_include_acl_is_opt_in_and_supports_key_selection() {
    let dir = tempfile::tempdir().unwrap();
    let home = dir.path().join("home");
    fs::create_dir_all(home.join(".openviking")).unwrap();
    fs::write(
        home.join(".openviking/ovcli.settings.conf"),
        json!({"language": "en"}).to_string(),
    )
    .unwrap();
    let uri = "viking://resources/docs/api.md";
    let acl = json!({
        "uri": uri,
        "acl_mode": "restricted",
        "direct_entries": [{"principal": "user:alice", "level": "manage"}],
        "inherited_entries": [{"principal": "user:*", "level": "read"}],
        "effective_entries": [{"principal": "user:alice", "level": "manage"}]
    });

    for (include_acl, key) in [
        (false, None),
        (true, None),
        (true, Some("acl")),
        (true, Some("acl.effective_entries")),
    ] {
        timeout(Duration::from_secs(10), async {
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let url = format!("http://{}", listener.local_addr().unwrap());
            let mut result = json!({
                "uri": uri, "context_type": "resource", "attrs": {"tags": ["team=search"]}
            });
            if include_acl {
                result["attrs"]["acl"] = acl.clone();
            }
            let expected = match key {
                Some("acl") => acl.clone(),
                Some("acl.effective_entries") => acl["effective_entries"].clone(),
                _ => result.clone(),
            };
            let body = json!({"status": "ok", "result": result}).to_string();
            let server = tokio::spawn(async move {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut request = Vec::new();
                while !request.windows(4).any(|bytes| bytes == b"\r\n\r\n") {
                    let mut chunk = [0; 4096];
                    let size = stream.read(&mut chunk).await.unwrap();
                    assert!(size > 0, "CLI closed before sending HTTP headers");
                    request.extend_from_slice(&chunk[..size]);
                }
                stream.write_all(format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                ).as_bytes()).await.unwrap();
                String::from_utf8(request).unwrap()
            });
            fs::write(
                dir.path().join("selected.json"),
                json!({"url": url, "timeout": 3, "echo_command": false}).to_string(),
            )
            .unwrap();
            let mut args = vec!["attrs", "get", uri, "-o", "json"];
            if include_acl {
                args.push("--include-acl");
            }
            if let Some(key) = key {
                args.push(key);
            }
            let output = Command::new(env!("CARGO_BIN_EXE_ov"))
                .current_dir(dir.path())
                // Isolate config, identity, language, and proxy settings from the host.
                .env_clear()
                .env("HOME", &home)
                .env("USERPROFILE", &home)
                .env("OPENVIKING_CLI_CONFIG_FILE", "selected.json")
                .env("OPENVIKING_LANG", "en")
                .env("NO_COLOR", "1")
                .args(args)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .kill_on_drop(true)
                .spawn()
                .unwrap()
                .wait_with_output()
                .await
                .unwrap();
            assert!(output.status.success(), "{output:?}");
            let request = server.await.unwrap();
            let mut request_line = request.lines().next().unwrap().split_whitespace();
            assert_eq!(request_line.next(), Some("GET"));
            let target = url::Url::parse(&format!(
                "http://localhost{}", request_line.next().unwrap()
            ))
            .unwrap();
            assert_eq!(target.path(), "/api/v1/fs/attrs");
            let mut expected_query = vec![("uri".to_string(), uri.to_string())];
            if include_acl {
                expected_query.push(("include_acl".to_string(), "true".to_string()));
            }
            assert_eq!(target.query_pairs().into_owned().collect::<Vec<_>>(), expected_query);
            let actual: Value = serde_json::from_slice(&output.stdout).unwrap();
            assert_eq!(actual["result"], expected);
        })
        .await
        .expect("attrs CLI integration request exceeded 10s");
    }
}
