[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("deploy", "status")]
    [string]$Action = "deploy"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ClusterName = "ax-sentinel-local"
$NodeGroupName = "ax-sentinel-workers"
$Namespace = "ax-sentinel"
$Registry = "000000000000.dkr.ecr.us-east-1.localhost.localstack.cloud:4566"
$Services = @(
    "asset-service",
    "incident-service",
    "ai-analysis-service",
    "knowledge-service",
    "work-order-service",
    "metrics-service",
    "web"
)

function Invoke-Awslocal {
    param([Parameter(ValueFromRemainingArguments)][string[]]$Arguments)

    & docker exec axsentinel-localstack awslocal @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "awslocal command failed: $($Arguments -join ' ')"
    }
}

function Wait-LocalStackEksResource {
    param(
        [ValidateSet("cluster", "nodegroup")]
        [string]$Resource,
        [string]$ExpectedStatus = "ACTIVE",
        [int]$Attempts = 120
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        if ($Resource -eq "cluster") {
            $status = (
                Invoke-Awslocal eks describe-cluster `
                    --name $ClusterName `
                    --query "cluster.status" `
                    --output text
            ).Trim()
        }
        else {
            $status = (
                Invoke-Awslocal eks describe-nodegroup `
                    --cluster-name $ClusterName `
                    --nodegroup-name $NodeGroupName `
                    --query "nodegroup.status" `
                    --output text
            ).Trim()
        }

        if ($status -eq $ExpectedStatus) {
            return
        }
        if ($status -eq "FAILED") {
            throw "LocalStack EKS $Resource entered FAILED status."
        }
        Start-Sleep -Seconds 2
    }

    throw "Timed out waiting for LocalStack EKS $Resource."
}

function Show-Status {
    Invoke-Awslocal eks describe-cluster `
        --name $ClusterName `
        --query "cluster.{name:name,status:status,version:version,endpoint:endpoint}"
    Invoke-Awslocal eks describe-nodegroup `
        --cluster-name $ClusterName `
        --nodegroup-name $NodeGroupName `
        --query "nodegroup.{name:nodegroupName,status:status,desired:scalingConfig.desiredSize}"
    kubectl get nodes
    kubectl get deployments,pods,services,ingress -n $Namespace
}

Push-Location $ProjectRoot
try {
    if ($Action -eq "status") {
        Show-Status
        return
    }

    if (-not $env:LOCALSTACK_AUTH_TOKEN) {
        throw "Set LOCALSTACK_AUTH_TOKEN in the current shell before deploying."
    }

    docker compose up -d --wait localstack
    if ($LASTEXITCODE -ne 0) {
        throw "LocalStack Pro failed to start."
    }

    $clusters = Invoke-Awslocal eks list-clusters --query "clusters" --output text
    if ($clusters -notmatch "(^|\s)$([regex]::Escape($ClusterName))(\s|$)") {
        $vpcId = (
            Invoke-Awslocal ec2 create-vpc `
                --cidr-block "10.80.0.0/16" `
                --query "Vpc.VpcId" `
                --output text
        ).Trim()
        $subnetId = (
            Invoke-Awslocal ec2 create-subnet `
                --vpc-id $vpcId `
                --cidr-block "10.80.1.0/24" `
                --query "Subnet.SubnetId" `
                --output text
        ).Trim()
        Invoke-Awslocal eks create-cluster `
            --name $ClusterName `
            --role-arn "arn:aws:iam::000000000000:role/ax-sentinel-eks-role" `
            --resources-vpc-config "subnetIds=$subnetId"
    }
    Wait-LocalStackEksResource -Resource cluster

    $nodeGroups = Invoke-Awslocal eks list-nodegroups `
        --cluster-name $ClusterName `
        --query "nodegroups" `
        --output text
    if ($nodeGroups -notmatch "(^|\s)$([regex]::Escape($NodeGroupName))(\s|$)") {
        $subnetId = (
            Invoke-Awslocal eks describe-cluster `
                --name $ClusterName `
                --query "cluster.resourcesVpcConfig.subnetIds[0]" `
                --output text
        ).Trim()
        Invoke-Awslocal eks create-nodegroup `
            --cluster-name $ClusterName `
            --nodegroup-name $NodeGroupName `
            --node-role "arn:aws:iam::000000000000:role/ax-sentinel-node-role" `
            --subnets $subnetId `
            --scaling-config "minSize=1,maxSize=2,desiredSize=1"
    }
    Wait-LocalStackEksResource -Resource nodegroup

    Invoke-Awslocal eks update-kubeconfig --name $ClusterName

    docker compose build $Services
    if ($LASTEXITCODE -ne 0) {
        throw "Container image build failed."
    }

    $repositories = (
        Invoke-Awslocal --region us-east-1 ecr describe-repositories `
            --query "repositories[].repositoryName" `
            --output text
    ) -join " "

    foreach ($service in $Services) {
        $repositoryName = "axsentinel/$service"
        if ($repositories -notmatch "(^|\s)$([regex]::Escape($repositoryName))(\s|$)") {
            Invoke-Awslocal --region us-east-1 ecr create-repository `
                --repository-name $repositoryName *> $null
            $repositories += " $repositoryName"
        }

        $source = "axsentinel/${service}:local"
        $target = "${Registry}/axsentinel/${service}:local"
        docker tag $source $target
        docker push $target
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to push $service to LocalStack ECR."
        }
    }

    helm upgrade --install ax-sentinel deploy/helm/ax-sentinel `
        --namespace $Namespace `
        --create-namespace `
        -f deploy/helm/ax-sentinel/values-localstack.yaml `
        --wait `
        --timeout 5m
    if ($LASTEXITCODE -ne 0) {
        throw "Helm deployment failed."
    }

    Show-Status
    Write-Host ""
    Write-Host "AX Sentinel LocalStack EKS is ready at http://localhost:8081"
}
finally {
    Pop-Location
}
