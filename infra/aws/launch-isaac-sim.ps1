param(
    [Parameter(Mandatory = $true)]
    [string]$AmiId,

    [Parameter(Mandatory = $true)]
    [string]$KeyName,

    [Parameter(Mandatory = $true)]
    [string]$SubnetId,

    [Parameter(Mandatory = $true)]
    [string]$SecurityGroupId,

    [string]$InstanceType = "g5.2xlarge",
    [string]$Name = "hades-isaac-sim",
    [int]$VolumeSizeGb = 250
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$userDataPath = Join-Path $scriptDir "user-data-isaac.sh"
$userData = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-Content -Raw -LiteralPath $userDataPath)))

aws ec2 run-instances `
    --image-id $AmiId `
    --instance-type $InstanceType `
    --key-name $KeyName `
    --subnet-id $SubnetId `
    --security-group-ids $SecurityGroupId `
    --user-data $userData `
    --block-device-mappings "[{`"DeviceName`":`"/dev/sda1`",`"Ebs`":{`"VolumeSize`":$VolumeSizeGb,`"VolumeType`":`"gp3`",`"DeleteOnTermination`":true}}]" `
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$Name},{Key=Project,Value=HADES},{Key=Phase,Value=1}]"
