# The only thing the API can run on a game server: apply its saved access settings. The document takes
# no parameters, so the API has no shell on the instance and passes it nothing to inject into.

resource "aws_ssm_document" "sync_access" {
  name          = "mc-ec2-sync-access"
  document_type = "Command"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Apply this server's saved access settings"
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "syncAccess"
      inputs = {
        timeoutSeconds = "960"
        runCommand     = ["/usr/local/bin/mc-sync-access"]
      }
    }]
  })
}
