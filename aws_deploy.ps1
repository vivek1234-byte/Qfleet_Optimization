# AWS Deployment Script for QFleet API
$ErrorActionPreference = "Stop"

$ACCOUNT_ID = "622111840104"
$REGION = "us-east-1"
$REPO_URL = "https://github.com/vivek1234-byte/Qfleet_Optimization.git"
$JWT_SECRET = -join ((48..122) | Get-Random -Count 48 | % {[char]$_})

Write-Host "Starting AWS Deployment Process..." -ForegroundColor Cyan

# Use ascii for AWS CLI json inputs to avoid BOM issues
# 1. IAM Role for CodeBuild
Write-Host "`n1. Creating IAM Role for CodeBuild..." -ForegroundColor Yellow
$trustPolicy = @'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "codebuild.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
'@
$trustPolicy | Out-File -FilePath cb-trust.json -Encoding ascii

try {
    aws iam create-role --role-name qfleet-codebuild-role --assume-role-policy-document file://cb-trust.json --query 'Role.Arn' --output text 2>$null
} catch {
    Write-Host "Role might already exist, continuing..." -ForegroundColor Gray
}

aws iam attach-role-policy --role-name qfleet-codebuild-role --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser
aws iam attach-role-policy --role-name qfleet-codebuild-role --policy-arn arn:aws:iam::aws:policy/CloudWatchLogsFullAccess

$CB_ROLE_ARN = aws iam get-role --role-name qfleet-codebuild-role --query 'Role.Arn' --output text
Start-Sleep -Seconds 10 

# 2. Create CodeBuild Project
Write-Host "`n2. Creating CodeBuild Project..." -ForegroundColor Yellow
$codebuildProject = @{
    name = "qfleet-build"
    source = @{
        type = "GITHUB"
        location = $REPO_URL
    }
    artifacts = @{ type = "NO_ARTIFACTS" }
    environment = @{
        type = "LINUX_CONTAINER"
        image = "aws/codebuild/standard:7.0"
        computeType = "BUILD_GENERAL1_SMALL"
        privilegedMode = $true
        environmentVariables = @(
            @{ name = "AWS_ACCOUNT_ID"; value = $ACCOUNT_ID }
        )
    }
    serviceRole = $CB_ROLE_ARN
}
$codebuildProject | ConvertTo-Json -Depth 5 | Out-File -FilePath cb-project.json -Encoding ascii

try {
    aws codebuild create-project --cli-input-json file://cb-project.json > $null
} catch {
    Write-Host "Project might already exist, updating..." -ForegroundColor Gray
    aws codebuild update-project --cli-input-json file://cb-project.json > $null
}

# 3. Start Build
Write-Host "`n3. Starting Image Build in CodeBuild..." -ForegroundColor Yellow
$buildId = aws codebuild start-build --project-name qfleet-build --query 'build.id' --output text

Write-Host "Build ID: $buildId. Waiting for build to complete (this will take 5-10 minutes)..."
$buildStatus = "IN_PROGRESS"
while ($buildStatus -eq "IN_PROGRESS") {
    Start-Sleep -Seconds 30
    $buildStatus = aws codebuild batch-get-builds --ids $buildId --query 'builds[0].buildStatus' --output text
    Write-Host "Status: $buildStatus"
}

if ($buildStatus -ne "SUCCEEDED") {
    Write-Host "Build failed! Please check CodeBuild console in AWS." -ForegroundColor Red
    exit
}

# 4. App Runner IAM Role
Write-Host "`n4. Creating IAM Role for App Runner..." -ForegroundColor Yellow
$arTrustPolicy = @'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "build.apprunner.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
'@
$arTrustPolicy | Out-File -FilePath ar-trust.json -Encoding ascii

try {
    aws iam create-role --role-name qfleet-apprunner-role --assume-role-policy-document file://ar-trust.json --query 'Role.Arn' --output text 2>$null
} catch {
    Write-Host "Role might already exist..." -ForegroundColor Gray
}

aws iam attach-role-policy --role-name qfleet-apprunner-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess
$AR_ROLE_ARN = aws iam get-role --role-name qfleet-apprunner-role --query 'Role.Arn' --output text
Start-Sleep -Seconds 10

# 5. Create App Runner Service
Write-Host "`n5. Creating App Runner Service..." -ForegroundColor Yellow
$appRunnerService = @{
    ServiceName = "qfleet-api"
    SourceConfiguration = @{
        AuthenticationConfiguration = @{
            AccessRoleArn = $AR_ROLE_ARN
        }
        AutoDeploymentsEnabled = $false
        ImageRepository = @{
            ImageIdentifier = "$($ACCOUNT_ID).dkr.ecr.$($REGION).amazonaws.com/qfleet-api:latest"
            ImageRepositoryType = "ECR"
            ImageConfiguration = @{
                Port = "8000"
                RuntimeEnvironmentVariables = @{
                    "QGF_JWT_SECRET" = $JWT_SECRET
                    "QGF_SEED_DEMO" = "true"
                    "QGF_CORS_ORIGINS" = "https://qfleetoptimization.vercel.app,http://localhost:5173"
                }
            }
        }
    }
    InstanceConfiguration = @{
        Cpu = "1 vCPU"
        Memory = "2 GB"
    }
}
$appRunnerService | ConvertTo-Json -Depth 5 | Out-File -FilePath ar-service.json -Encoding ascii

$serviceOutput = aws apprunner create-service --cli-input-json file://ar-service.json
$serviceUrl = ($serviceOutput | ConvertFrom-Json).Service.ServiceUrl

# Cleanup
Remove-Item cb-trust.json, cb-project.json, ar-trust.json, ar-service.json -ErrorAction SilentlyContinue

Write-Host "`n========================================================" -ForegroundColor Green
Write-Host "Deployment Initiated!" -ForegroundColor Green
Write-Host "Your API URL will be: https://$serviceUrl" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
