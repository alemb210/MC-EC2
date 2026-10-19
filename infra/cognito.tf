# Cognito user pool that issues the access tokens the API verifies (proposal section IV-C).

resource "aws_cognito_user_pool" "main" {
  name                     = "mc-ec2"
  username_attributes      = ["email"] # sign in with email; cannot be changed after creation
  auto_verified_attributes = ["email"]
  deletion_protection      = "ACTIVE"

  username_configuration {
    case_sensitive = false
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  # Self-signup is on: the hosted login page shows "Sign up". GET /servers and POST /servers register
  # new users in the database; MAX_SERVERS_* in lambda.tf caps what they can launch.
  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Public client for the browser app: no secret, authorization code + PKCE.
resource "aws_cognito_user_pool_client" "web" {
  name            = "mc-ec2-web"
  user_pool_id    = aws_cognito_user_pool.main.id
  generate_secret = false

  # USER_PASSWORD_AUTH lets the team get tokens from the CLI for testing.
  explicit_auth_flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_PASSWORD_AUTH"]

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email"]
  # localhost for `npm run dev`; the API URL is where Lambda serves the built frontend.
  callback_urls                        = ["http://localhost:3000/", "${aws_apigatewayv2_api.api.api_endpoint}/"]
  logout_urls                          = ["http://localhost:3000/", "${aws_apigatewayv2_api.api.api_endpoint}/"]
  supported_identity_providers         = ["COGNITO"]

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

# Hosted login pages at https://mc-ec2-<account id>.auth.us-east-1.amazoncognito.com
resource "aws_cognito_user_pool_domain" "main" {
  domain                = "mc-ec2-${data.aws_caller_identity.current.account_id}"
  user_pool_id          = aws_cognito_user_pool.main.id
  managed_login_version = 1
}

# The single admin account. Cognito emails a temporary password; no password is stored in Terraform.
resource "aws_cognito_user" "admin" {
  user_pool_id             = aws_cognito_user_pool.main.id
  username                 = var.admin_email
  desired_delivery_mediums = ["EMAIL"]

  attributes = {
    email          = var.admin_email
    email_verified = "true"
  }
}
