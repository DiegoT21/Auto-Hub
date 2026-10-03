# Sage 50 SDK host for Windows Smart App Control.
# Unsigned csc.exe output is blocked (WinError 4551). This runs inside
# signed 32-bit powershell.exe and only loads Sage's own DLLs.
param(
    [Parameter(Mandatory = $true)][string]$Company,
    [Parameter(Mandatory = $true)][string]$AppIdFile,
    [string]$SampleJson = "",
    [string]$CustomerId = "",
    [string]$CustomerName = "",
    [switch]$AuthOnly,
    [switch]$DeleteAh,
    [string]$OnlySeq = "",
    [switch]$ProbeItems
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class AhHideHost {
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern int SetWindowLong(IntPtr h, int n, int v);
    public static void Hide() {
        IntPtr h = GetConsoleWindow();
        if (h == IntPtr.Zero) return;
        ShowWindow(h, 0);
        int ex = GetWindowLong(h, -20);
        SetWindowLong(h, -20, (ex | 0x00000080) & ~0x00040000);
        ShowWindow(h, 0);
    }
}
"@ -ErrorAction Stop
    [AhHideHost]::Hide()
} catch { }
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SampleJson) {
    $SampleJson = Join-Path $scriptDir "sample_invoice.json"
}
if ($env:AUTOHUB_SAGE_HOST_LOG) {
    try { Start-Transcript -Path $env:AUTOHUB_SAGE_HOST_LOG -Force | Out-Null } catch {}
}

function Fail([int]$code, [string]$msg) {
    if ($script:LastAhFail) { Write-Host ("[TRACE] ultimo_fail: " + $script:LastAhFail) }
    elseif ($script:LastAhTrace) { Write-Host ("[TRACE] ultimo_paso: " + $script:LastAhTrace) }
    Write-Host "ERROR: $msg"
    exit $code
}

function Write-AhTrace {
    param(
        [string]$Fn,
        [string]$Paso,
        [string]$Sku = "",
        [string]$Detail = "",
        [string]$Linea = "",
        $Ok = $null
    )
    $t = Get-Date -Format "HH:mm:ss.fff"
    $flag = ".."
    if ($Ok -eq $true) { $flag = "OK" }
    elseif ($Ok -eq $false) { $flag = "FAIL" }
    $bits = "[TRACE] t=$t fn=$Fn paso=$Paso"
    if ($Linea) { $bits += " linea=$Linea" }
    if ($Sku) { $bits += " sku=$Sku" }
    $bits += " $flag $Detail"
    $script:LastAhTrace = $bits
    if ($Ok -eq $false) { $script:LastAhFail = $bits }
    Write-Host $bits
}

function Get-SageProp($obj, [string]$name) {
    if ($null -eq $obj) { return $null }
    try {
        $flags = [Reflection.BindingFlags]"Instance,Public,IgnoreCase"
        $p = $obj.GetType().GetProperty($name, $flags)
        if ($null -eq $p) { return $null }
        return $p.GetValue($obj, $null)
    }
    catch {
        return $null
    }
}

function Set-SageProp($obj, [string]$name, $value) {
    if ($null -eq $obj -or $null -eq $value) { return $false }
    try {
        $flags = [Reflection.BindingFlags]"Instance,Public,IgnoreCase"
        $p = $obj.GetType().GetProperty($name, $flags)
        if ($null -eq $p -or -not $p.CanWrite) { return $false }
        $target = $p.PropertyType
        $under = [Nullable]::GetUnderlyingType($target)
        if ($under) { $target = $under }
        $coerced = $value
        try {
            if ($target -eq [decimal]) { $coerced = [decimal]$value }
            elseif ($target -eq [double]) { $coerced = [double]$value }
            elseif ($target -eq [int]) { $coerced = [int]$value }
            elseif ($target -eq [bool]) { $coerced = [bool]$value }
            elseif ($target -eq [datetime]) { $coerced = [datetime]$value }
            elseif ($target -eq [string]) { $coerced = [string]$value }
        }
        catch {
            $coerced = $value
        }
        $p.SetValue($obj, $coerced, $null)
        return $true
    }
    catch {
        Write-Host ("    AVISO set " + $name + ": " + $_.Exception.Message)
        return $false
    }
}

function Invoke-SageMethod($obj, [string]$name) {
    if ($null -eq $obj) { return $null }
    try {
        $m = $obj.GetType().GetMethod($name, [Type]::EmptyTypes)
        if ($null -eq $m) {
            $m = $obj.GetType().GetMethods() | Where-Object {
                $_.Name -eq $name -and $_.GetParameters().Count -eq 0
            } | Select-Object -First 1
        }
        if ($null -eq $m) { return $null }
        return $m.Invoke($obj, $null)
    }
    catch {
        Write-Host ("    AVISO " + $name + "(): " + $_.Exception.Message)
        return $null
    }
}

function Get-InvoiceRecords([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "No existe el JSON de factura: $path"
    }
    $raw = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $payload = $raw | ConvertFrom-Json
    $records = @()
    foreach ($item in @($payload)) {
        if ($null -eq $item) { continue }
        if ($item.PSObject.Properties.Name -contains "record" -and $item.record) {
            $records += $item.record
        }
        elseif ($item.PSObject.Properties.Name -contains "factura_id") {
            $records += $item
        }
    }
    return @($records)
}

function Get-RecordText($rec, [string]$name) {
    $p = $rec.PSObject.Properties[$name]
    if ($null -eq $p -or $null -eq $p.Value) { return "" }
    return [string]$p.Value
}

function Get-RecordDecimal($rec, [string]$name, [decimal]$fallback) {
    $p = $rec.PSObject.Properties[$name]
    if ($null -eq $p -or $null -eq $p.Value -or "$($p.Value)" -eq "") { return $fallback }
    try {
        return [decimal]::Parse("$($p.Value)", [Globalization.CultureInfo]::InvariantCulture)
    }
    catch {
        return $fallback
    }
}

function Round-Money([decimal]$value) {
    return [decimal]::Round($value, 2, [MidpointRounding]::AwayFromZero)
}

function Get-InvoiceDiscount($records) {
    $sum = [decimal]0
    $pct = [decimal]0
    foreach ($rec in @($records)) {
        $du = Get-RecordDecimal $rec "dsctounit" 0
        $qty = Get-RecordDecimal $rec "cantidad" 1
        $sum += $du * $qty
        if ($pct -eq 0) {
            $p = Get-RecordDecimal $rec "dsctoprc" 0
            if ($p -eq 0) { $p = Get-RecordDecimal $rec "desctoprc" 0 }
            if ($p -ne 0) { $pct = $p }
        }
    }
    return @{ Amount = (Round-Money $sum); Pct = $pct }
}

function Format-DescuentoDesc([decimal]$pct) {
    if ($pct -eq 0) { return "Descuento" }
    $shown = $pct
    if ($shown -gt 0 -and $shown -lt 1) { $shown = $shown * 100 }
    $n = [int][decimal]::Round($shown, 0, [MidpointRounding]::AwayFromZero)
    if ($n -le 0) { return "Descuento" }
    return "Descuento $n%"
}

function Get-PsKloudInvoiceId($first) {
    $id = Get-RecordText $first "factura_id"
    $num = Get-RecordText $first "numero_factura"
    $blob = ($id + " " + $num)
    $m = [regex]::Match($blob, '(C\d{7}|\*\d{7,})')
    if ($m.Success) { return $m.Value }
    foreach ($candidate in @($id, $num)) {
        if ($candidate -and $candidate.Length -le 12 -and $candidate -notmatch '^FE') { return $candidate }
    }
    if ($num -and $num.Length -le 12) { return $num }
    $safe = ($id -replace '[^A-Za-z0-9*]', '')
    if ($safe.Length -gt 8) { $safe = $safe.Substring($safe.Length - 8) }
    return $safe
}

function Get-ShortDocumento($first) {
    if ($null -eq $first) { return "" }
    $id = Get-RecordText $first "factura_id"
    $num = Get-RecordText $first "numero_factura"
    $blob = ($id + " " + $num)
    $m = [regex]::Match($blob, '(C\d{7}|\*\d{7,})')
    if ($m.Success) { return $m.Value }
    foreach ($candidate in @($id, $num)) {
        if (-not $candidate) { continue }
        $tail = $candidate
        if ($tail.Contains(":")) { $tail = $tail.Substring($tail.LastIndexOf(":") + 1) }
        if ($tail -and $tail.Length -le 12 -and $tail -notmatch '^FE') { return $tail }
    }
    return ""
}

function Get-SageLetterFromDoc([string]$doc) {
    if (-not $doc) { return "" }
    $ch = $doc.Substring(0, 1)
    if ($ch -eq "C" -or $ch -eq "c") { return "C" }
    if ($ch -eq "*") { return "R" }
    if ($ch -match "^\d$") { return "A" }
    return "S"
}

function Get-SageStoreLetter([string]$sucursal, $first = $null) {
    $s = if ($sucursal) { $sucursal.ToUpperInvariant() } else { "" }
    if ($s -match "RIO ABAJO") { return "R" }
    if ($s -match "CORONADO") { return "C" }
    if ($s -match "ADI") { return "A" }
    $fromSuc = Get-SageLetterFromDoc $sucursal
    if ($fromSuc -and $fromSuc -ne "S") { return $fromSuc }
    $doc = Get-ShortDocumento $first
    $fromDoc = Get-SageLetterFromDoc $doc
    if ($fromDoc) { return $fromDoc }
    return "S"
}

function Get-SageStoreGlIds([string]$letter) {
    switch ($letter) {
        "R" { return @{ Sales = "4001"; Discount = "4031"; Name = "SIKA CENTER RIO ABAJO" } }
        "C" { return @{ Sales = "4002"; Discount = "4032"; Name = "CORONADO" } }
        "A" { return @{ Sales = "4003"; Discount = "4033"; Name = "ADI SUPPLY" } }
        default { return @{ Sales = ""; Discount = ""; Name = "SIN SUCURSAL" } }
    }
}

function Get-SageInvoiceSeqDigits([string]$text) {
    if (-not $text) { return "" }
    $m = [regex]::Match($text, '(C|\*)(\d{5,})')
    if ($m.Success) { return $m.Groups[2].Value }
    $m2 = [regex]::Match($text, '(\d{5,})')
    if ($m2.Success) { return $m2.Groups[1].Value }
    return ""
}

function Get-SageInvoiceSeq($first) {
    # Preferir documento / cola despues de FAC: — si se busca el primer \d{5,}
    # en factura_id (000002:001:FAC:00011222) se toma la empresa 000002 y todas
    # las ADI chocan en AH-fecha-A-00002.
    $digits = ""
    $doc = Get-RecordText $first "documento"
    if ($doc) {
        $digits = Get-SageInvoiceSeqDigits $doc
    }
    if (-not $digits) {
        $id = Get-RecordText $first "factura_id"
        if ($id -and $id.Contains(":")) {
            $tail = $id.Substring($id.LastIndexOf(":") + 1)
            $digits = Get-SageInvoiceSeqDigits $tail
        }
    }
    if (-not $digits) {
        $id = Get-RecordText $first "factura_id"
        $num = Get-RecordText $first "numero_factura"
        $digits = Get-SageInvoiceSeqDigits ($id + " " + $num)
    }
    if (-not $digits) { $digits = "0" }
    if ($digits.Length -gt 5) { $digits = $digits.Substring($digits.Length - 5) }
    return $digits.PadLeft(5, [char]'0')
}

function Get-SageInvoiceNo($first, [string]$store, [datetime]$fecha) {
    $letter = if ($store -and $store.Length -eq 1) { $store } else { Get-SageStoreLetter "" $first }
    $day = $fecha.ToString("ddMMyy")
    $seq = Get-SageInvoiceSeq $first
    $ref = "AH" + $day + "-" + $letter + "-" + $seq
    if ($ref.Length -gt 20) { $ref = $ref.Substring(0, 20) }
    return $ref
}

function Normalize-Person([string]$value) {
    if (-not $value) { return "" }
    $t = $value.ToUpperInvariant().Trim()
    $t = [regex]::Replace($t, "[^A-Z0-9]+", " ")
    return [regex]::Replace($t, "\s+", " ").Trim()
}

function Show-SageCustomers($customers, [int]$limit = 25) {
    if (-not $customers) {
        Write-Host "  (no se pudieron cargar clientes)"
        return
    }
    $i = 0
    foreach ($c in $customers) {
        $i++
        if ($i -gt $limit) {
            Write-Host ("  ... +" + ($customers.Count - $limit) + " mas")
            break
        }
        Write-Host ("  " + $c.ID + " | " + $c.Name)
    }
}

function Save-SageEntity($entity) {
    $m = $entity.GetType().GetMethod("Save", [Type]::EmptyTypes)
    if ($null -eq $m) {
        throw "Save() no existe en " + $entity.GetType().Name
    }
    try {
        $m.Invoke($entity, $null) | Out-Null
    }
    catch {
        $inner = $_.Exception
        if ($inner.InnerException) { $inner = $inner.InnerException }
        throw $inner
    }
}

function Get-TemplateCustomer($customers) {
    if (-not $customers) { return $null }
    foreach ($want in @("CONTADO", "CREDITO", "CLIENTE CONTADO PA")) {
        $norm = Normalize-Person $want
        foreach ($c in $customers) {
            if ((Normalize-Person $c.Name) -ne $norm -and (Normalize-Person $c.ID) -ne $norm) { continue }
            try {
                if ($c.UsualSalesAccountReference) { return $c }
            }
            catch { }
        }
    }
    foreach ($c in $customers) {
        try {
            if ($c.UsualSalesAccountReference) { return $c }
        }
        catch { }
    }
    return $null
}

function New-SageCustomerId([string]$id, [string]$name) {
    $raw = if ($id) { $id.Trim() } else { $name.Trim() }
    if (-not $raw) {
        return "AH" + (Get-Date).ToString("yyMMddHHmmss")
    }
    if ($raw.Length -gt 20) { $raw = $raw.Substring(0, 20) }
    return $raw
}

function Clip-SageText([string]$text, [int]$max) {
    if (-not $text) { return "" }
    $t = $text.Trim()
    if ($t.Length -gt $max) { return $t.Substring(0, $max) }
    return $t
}

function Dump-SageType($obj, [string]$label) {
    if ($null -eq $obj) {
        Write-Host ("  " + $label + ": (null)")
        return
    }
    try {
        $props = $obj.GetType().GetProperties([Reflection.BindingFlags]"Instance,Public") |
            ForEach-Object { $_.Name } | Sort-Object
        Write-Host ("  " + $label + " props: " + ($props -join ", "))
    }
    catch {
        Write-Host ("  " + $label + " dump: " + $_.Exception.Message)
    }
}

function Set-SageAddressLine1($addr, [string]$line1) {
    if ($null -eq $addr -or -not $line1) { return $false }
    foreach ($name in @("AddressLine1", "Address1", "Line1", "Street1", "Street")) {
        if (Set-SageProp $addr $name $line1) { return $true }
    }
    return $false
}

function Fill-SageContactRequired($company, $cust, [string]$name, [string]$address) {
    # Sage 50 no deja guardar el contacto (Bill-To) si Last name, Company name
    # y Address line 1 van vacios. Customer.Name no alcanza.
    $companyName = Clip-SageText $name 40
    if (-not $companyName) { $companyName = "CLIENTE" }
    $last = Clip-SageText $name 20
    $line1 = Clip-SageText $(if ($address) { $address } else { $companyName }) 30
    $filled = @()

    foreach ($pair in @(
            @("CompanyName", $companyName),
            @("LastName", $last),
            @("ContactName", $companyName)
        )) {
        if (Set-SageProp $cust $pair[0] $pair[1]) { $filled += $pair[0] }
    }

    foreach ($addrName in @("BillToAddress", "ShipToAddress", "MailingAddress", "Address")) {
        $addr = Get-SageProp $cust $addrName
        if ($null -eq $addr) { continue }
        if (Set-SageAddressLine1 $addr $line1) {
            Set-SageProp $cust $addrName $addr | Out-Null
            $filled += ($addrName + ".Address1")
        }
    }

    foreach ($cName in @("BillToContact", "ShipToContact", "MailToContact", "Contact", "PrimaryContact", "MainContact")) {
        $ct = Get-SageProp $cust $cName
        if ($null -eq $ct) { continue }
        if (Set-SageProp $ct "CompanyName" $companyName) { $filled += ($cName + ".CompanyName") }
        if (Set-SageProp $ct "LastName" $last) { $filled += ($cName + ".LastName") }
        if (Set-SageProp $ct "Name" $companyName) { $filled += ($cName + ".Name") }
        $caddr = Get-SageProp $ct "Address"
        if ($caddr -and (Set-SageAddressLine1 $caddr $line1)) {
            Set-SageProp $ct "Address" $caddr | Out-Null
            $filled += ($cName + ".Address")
        }
        Set-SageProp $cust $cName $ct | Out-Null
    }

    $contacts = Get-SageProp $cust "Contacts"
    $hadContact = $false
    if ($null -ne $contacts) {
        try {
            foreach ($ct in @($contacts)) {
                if ($null -eq $ct) { continue }
                $hadContact = $true
                Set-SageProp $ct "CompanyName" $companyName | Out-Null
                Set-SageProp $ct "LastName" $last | Out-Null
                $caddr = Get-SageProp $ct "Address"
                if ($caddr) { Set-SageAddressLine1 $caddr $line1 | Out-Null }
            }
        }
        catch { }
        if (-not $hadContact) {
            $added = Invoke-SageMethod $contacts "Add"
            if ($added) {
                Set-SageProp $added "CompanyName" $companyName | Out-Null
                Set-SageProp $added "LastName" $last | Out-Null
                $caddr = Get-SageProp $added "Address"
                if ($caddr) { Set-SageAddressLine1 $caddr $line1 | Out-Null }
                $filled += "Contacts.Add"
            }
        }
    }

    $bill = Get-SageProp $cust "BillToContact"
    if ($null -eq $bill) {
        $factories = Get-SageProp $company "Factories"
        $cf = Get-SageProp $factories "ContactFactory"
        $ct = Invoke-SageMethod $cf "Create"
        if ($ct) {
            Set-SageProp $ct "CompanyName" $companyName | Out-Null
            Set-SageProp $ct "LastName" $last | Out-Null
            $caddr = Get-SageProp $ct "Address"
            if ($caddr) { Set-SageAddressLine1 $caddr $line1 | Out-Null }
            if (Set-SageProp $cust "BillToContact" $ct) { $filled += "ContactFactory.BillToContact" }
        }
    }

    if ($filled.Count -gt 0) {
        Write-Host ("  Contacto Sage: " + ($filled -join "; "))
    }
    else {
        Write-Host "  AVISO: Sage no expuso CompanyName/LastName/Address1 en el Customer."
        Dump-SageType $cust "Customer"
        Dump-SageType (Get-SageProp $cust "BillToContact") "BillToContact"
        Dump-SageType (Get-SageProp $cust "BillToAddress") "BillToAddress"
        Dump-SageType (Get-SageProp $cust "Contacts") "Contacts"
    }
}

function New-SageCustomer($company, [string]$id, [string]$name, [string]$ruc, $template, [string]$address) {
    $factory = $company.Factories.CustomerFactory
    $cust = $null
    foreach ($method in @("Create", "CreateCustomer", "NewCustomer")) {
        $cust = Invoke-SageMethod $factory $method
        if ($null -ne $cust) { break }
    }
    if ($null -eq $cust) {
        throw "no se pudo Create() Customer en Sage"
    }
    $safeId = New-SageCustomerId $id $name
    $safeName = if ($name) { $name.Trim() } else { $safeId }
    if ($safeName.Length -gt 52) { $safeName = $safeName.Substring(0, 52) }
    Set-SageProp $cust "ID" $safeId | Out-Null
    Set-SageProp $cust "Name" $safeName | Out-Null
    if ($ruc) {
        Set-SageProp $cust "AccountNumber" $ruc | Out-Null
        Set-SageProp $cust "TaxID" $ruc | Out-Null
        Set-SageProp $cust "CustomField1" $ruc | Out-Null
    }
    if ($template) {
        try {
            $gl = $template.UsualSalesAccountReference
            if ($gl) {
                Set-SageProp $cust "UsualSalesAccountReference" $gl | Out-Null
            }
        }
        catch {
            Write-Host ("  AVISO copiar GL del cliente plantilla: " + $_.Exception.Message)
        }
    }
    Fill-SageContactRequired $company $cust $safeName $address
    Write-Host ("  Guardando cliente nuevo: " + $safeId + " | " + $safeName)
    try {
        Save-SageEntity $cust
    }
    catch {
        Dump-SageType $cust "Customer (Save fallo)"
        Dump-SageType (Get-SageProp $cust "BillToContact") "BillToContact"
        Dump-SageType (Get-SageProp $cust "BillToAddress") "BillToAddress"
        throw
    }
    return $cust
}

function Find-SageCustomer($company, [string[]]$ids, [string[]]$names, [ref]$allOut) {
    $list = $company.Factories.CustomerFactory.List()
    try { $list.Load() } catch { }
    $customers = @($list)
    if ($allOut) { $allOut.Value = $customers }
    Write-Host ("  Clientes en Sage: " + $customers.Count)

    $idSet = @($ids | Where-Object { $_ } | ForEach-Object { $_.Trim() } | Select-Object -Unique)
    $nameSet = @($names | Where-Object { $_ } | ForEach-Object { Normalize-Person $_ } | Where-Object { $_ } | Select-Object -Unique)

    foreach ($id in $idSet) {
        foreach ($c in $customers) {
            if ([string]::Equals($c.ID, $id, [StringComparison]::OrdinalIgnoreCase)) {
                Write-Host ("  Match por ID exacto: " + $c.ID)
                return $c
            }
        }
    }

    foreach ($want in $nameSet) {
        foreach ($c in $customers) {
            if ((Normalize-Person $c.Name) -eq $want -or (Normalize-Person $c.ID) -eq $want) {
                Write-Host ("  Match por nombre exacto: " + $c.ID + " | " + $c.Name)
                return $c
            }
        }
    }

    foreach ($want in $nameSet) {
        if ($want.Length -lt 6) { continue }
        # Solo prefijo claro: "BUILDERS STEEL CO" vs "BUILDERS STEEL COMPANY".
        # Contains suelto pegaba JHON OROZCO -> LINA OROZCO y PC SOLUTION -> CM SOLUTION.
        $prefixHits = @{}
        foreach ($c in $customers) {
            $cn = Normalize-Person $c.Name
            if (-not $cn) { continue }
            $shorter = if ($cn.Length -le $want.Length) { $cn } else { $want }
            $longer = if ($cn.Length -gt $want.Length) { $cn } else { $want }
            if ($shorter.Length -lt 6) { continue }
            if ($longer.StartsWith($shorter) -and ($longer.Length -eq $shorter.Length -or $longer[$shorter.Length] -eq [char]' ')) {
                $prefixHits[$c.ID] = $c
            }
        }
        if ($prefixHits.Count -eq 1) {
            $one = @($prefixHits.Values)[0]
            Write-Host ("  Match por prefijo de nombre: " + $one.ID + " | " + $one.Name)
            return $one
        }
        if ($prefixHits.Count -gt 1) {
            Write-Host ("  AVISO prefijo '" + $want + "' coincide con " + $prefixHits.Count + " clientes; no se adivina.")
        }
    }

    foreach ($id in $idSet) {
        $compact = $id -replace "[^0-9A-Za-z]", ""
        if ($compact.Length -lt 4) { continue }
        foreach ($c in $customers) {
            $cid = ($c.ID -replace "[^0-9A-Za-z]", "")
            if ($cid -and [string]::Equals($cid, $compact, [StringComparison]::OrdinalIgnoreCase)) {
                Write-Host ("  Match por codigo compacto: " + $c.ID + " | " + $c.Name)
                return $c
            }
        }
    }

    # Sin match seguro: el caller crea cliente nuevo. No adivinar por apellido.
    Write-Host "  Sin match seguro de cliente (ID/nombre exacto o prefijo unico)."
    return $null
}

function New-SageInvoice($company) {
    $factories = Get-SageProp $company "Factories"
    foreach ($name in @("SalesInvoiceFactory", "SalesJournalFactory", "InvoiceFactory")) {
        $factory = Get-SageProp $factories $name
        if ($null -eq $factory) { continue }
        Write-Host ("  Factory: " + $name + " (" + $factory.GetType().Name + ")")
        foreach ($method in @("Create", "CreateSalesInvoice", "NewSalesInvoice")) {
            $invoice = Invoke-SageMethod $factory $method
            if ($null -ne $invoice) { return $invoice }
        }
    }
    return $null
}

function Add-SageInvoiceLine($invoice, $company) {
    foreach ($name in @("AddLine", "AddSalesLine", "AddDistribution", "AddSalesInvoiceLine", "CreateLine")) {
        $line = Invoke-SageMethod $invoice $name
        if ($null -ne $line) { return $line }
    }
    foreach ($cname in @("Lines", "SalesLines", "Distributions", "LineItems")) {
        $coll = Get-SageProp $invoice $cname
        if ($null -eq $coll) { continue }
        $added = Invoke-SageMethod $coll "Add"
        if ($null -ne $added) { return $added }
    }
    return $null
}

function Get-SageAccountRef($acct) {
    if ($null -eq $acct) { return $null }
    try {
        $k = $acct.Key
        if ($null -ne $k) { return $k }
    }
    catch { }
    return $acct
}

function Find-SageGlAccount($company, [string]$acctId) {
    if (-not $acctId) { return $null }
    $want = $acctId.Trim()
    $factories = Get-SageProp $company "Factories"
    if ($null -eq $factories) { return $null }
    foreach ($fname in @("GLAccountFactory", "AccountFactory", "GeneralLedgerAccountFactory", "ChartOfAccountsFactory")) {
        $factory = Get-SageProp $factories $fname
        if ($null -eq $factory) { continue }
        try {
            $loaded = $factory.Load($want)
            if ($null -ne $loaded) {
                Write-Host ("GL Sage Load " + $fname + ": " + $want)
                return $loaded
            }
        }
        catch { }
        $list = $null
        try { $list = $factory.List() } catch { $list = Invoke-SageMethod $factory "List" }
        if ($null -eq $list) { continue }
        try { $list.Load() } catch { try { Invoke-SageMethod $list "Load" | Out-Null } catch {} }
        foreach ($a in @($list)) {
            $id = [string](Get-SageProp $a "ID")
            if ($id -and [string]::Equals($id.Trim(), $want, [StringComparison]::OrdinalIgnoreCase)) {
                Write-Host ("GL Sage List " + $fname + ": " + $want)
                return $a
            }
        }
    }
    return $null
}

function Set-SageLineGl($line, $acctRef) {
    if ($null -eq $line -or $null -eq $acctRef) { return $false }
    $ok = $false
    foreach ($p in @("AccountReference", "GLAccountReference", "SalesAccountReference")) {
        if (Set-SageProp $line $p $acctRef) { $ok = $true }
    }
    return $ok
}

function Find-SageSalesTax($company, [string]$wantId) {
    $factories = Get-SageProp $company "Factories"
    if ($null -eq $factories) { return $null }
    foreach ($fname in @("SalesTaxCodeFactory", "SalesTaxFactory", "TaxCodeFactory", "SalesTaxTableFactory")) {
        $factory = Get-SageProp $factories $fname
        if ($null -eq $factory) { continue }
        Write-Host ("  Factory impuesto: " + $fname)
        $list = $null
        try { $list = $factory.List() } catch { $list = Invoke-SageMethod $factory "List" }
        if ($null -eq $list) { continue }
        try { $list.Load() } catch { try { Invoke-SageMethod $list "Load" | Out-Null } catch {} }
        foreach ($t in @($list)) {
            $id = [string](Get-SageProp $t "ID")
            $name = [string](Get-SageProp $t "Description")
            if (-not $name) { $name = [string](Get-SageProp $t "Name") }
            Write-Host ("    codigo impuesto: " + $id + " | " + $name)
            if ($id -and [string]::Equals($id.Trim(), $wantId, [StringComparison]::OrdinalIgnoreCase)) {
                return $t
            }
        }
    }
    return $null
}

function Get-RecordItemCodigo($rec) {
    foreach ($name in @("item_codigo", "codigo", "itemCode", "itemCodigo", "sku", "coditem")) {
        $v = Get-RecordText $rec $name
        if ($v) { return $v.Trim() }
    }
    return ""
}

function Get-SageItemLabel($item) {
    foreach ($p in @("Description", "SalesDescription", "Name", "ItemDescription")) {
        $v = [string](Get-SageProp $item $p)
        if ($v) { return $v.Trim() }
    }
    return ""
}

function Normalize-ItemName([string]$value) {
    if (-not $value) { return "" }
    $t = $value.ToUpperInvariant()
    $t = [regex]::Replace($t, "[^A-Z0-9]+", " ")
    $t = [regex]::Replace($t, "(\d)\s+(ML|LTS|LTR|LT|KG|GL|G|MM|CM)\b", '$1$2')
    $words = @()
    foreach ($w in [regex]::Split($t, "\s+")) {
        if (-not $w) { continue }
        if ($w -in @("DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "THE", "OF", "A", "B")) { continue }
        $words += $w
    }
    return ($words -join " ")
}

function Get-ItemSizeTokens([string]$norm) {
    $out = @()
    foreach ($m in [regex]::Matches($norm, "\d+(ML|LTS|LTR|LT|KG|GL|G|MM|CM)")) {
        $out += $m.Value
    }
    return $out
}

function Test-ItemNameMatch([string]$wantRaw, [string]$haveRaw) {
    $want = Normalize-ItemName $wantRaw
    $have = Normalize-ItemName $haveRaw
    if (-not $want -or -not $have) { return $false }
    if ($want -eq $have) { return $true }

    $wantSizes = @(Get-ItemSizeTokens $want)
    $haveSizes = @(Get-ItemSizeTokens $have)
    if ($wantSizes.Count -gt 0 -and $haveSizes.Count -gt 0) {
        foreach ($s in $wantSizes) {
            if ($haveSizes -notcontains $s) { return $false }
        }
        foreach ($s in $haveSizes) {
            if ($wantSizes -notcontains $s) { return $false }
        }
    }

    if ($have.IndexOf($want) -ge 0 -or $want.IndexOf($have) -ge 0) { return $true }

    $wantWords = @($want.Split([char]' ') | Where-Object { $_ })
    $haveWords = @($have.Split([char]' ') | Where-Object { $_ })
    if ($wantWords.Count -ge 2) {
        $all = $true
        foreach ($w in $wantWords) {
            if ($have.IndexOf($w) -lt 0) { $all = $false; break }
        }
        if ($all) { return $true }
    }
    # Sage Description max 30 chars: the short Sage name is often inside the PsKloud name.
    if ($haveWords.Count -ge 2) {
        $all = $true
        foreach ($w in $haveWords) {
            if ($want.IndexOf($w) -lt 0) { $all = $false; break }
        }
        if ($all) { return $true }
    }
    $clipWant = Normalize-ItemName (Clip-SageText $wantRaw 30)
    if ($clipWant -and ($clipWant -eq $have -or $have.IndexOf($clipWant) -ge 0 -or $clipWant.IndexOf($have) -ge 0)) {
        return $true
    }
    return $false
}

function Find-SageInventoryItem($company, [string]$itemId, [string]$desc, [ref]$cache) {
    $wantId = if ($itemId) { $itemId.Trim() } else { "" }
    $items = $null
    if ($cache -and $null -ne $cache.Value) {
        $items = $cache.Value
    }
    else {
        $factories = Get-SageProp $company "Factories"
        if ($null -eq $factories) { return $null }
        foreach ($fname in @("InventoryItemFactory", "ItemFactory", "InventoryFactory")) {
            $factory = Get-SageProp $factories $fname
            if ($null -eq $factory) { continue }
            Write-Host ("  Factory inventario: " + $fname)
            if ($wantId) {
                try {
                    $loaded = $factory.Load($wantId)
                    if ($null -ne $loaded) {
                        Write-Host ("[ITEM] MATCH ID: " + $wantId + " | " + (Get-SageItemLabel $loaded))
                        return $loaded
                    }
                }
                catch { }
            }
            $list = $null
            try { $list = $factory.List() } catch { $list = Invoke-SageMethod $factory "List" }
            if ($null -eq $list) { continue }
            try { $list.Load() } catch { try { Invoke-SageMethod $list "Load" | Out-Null } catch {} }
            $items = @($list)
            break
        }
        if ($cache) { $cache.Value = $items }
    }
    if (-not $items) { return $null }

    if ($wantId) {
        foreach ($it in @($items)) {
            $id = [string](Get-SageProp $it "ID")
            if ($id -and [string]::Equals($id.Trim(), $wantId, [StringComparison]::OrdinalIgnoreCase)) {
                Write-Host ("[ITEM] MATCH ID: " + $id + " | " + (Get-SageItemLabel $it))
                return $it
            }
        }
    }

    if (-not $desc) {
        Write-Host ("[ITEM] NO MATCH: codigo=" + $wantId + " (sin descripcion)")
        return $null
    }
    $hits = @()
    foreach ($it in @($items)) {
        $label = Get-SageItemLabel $it
        $id = [string](Get-SageProp $it "ID")
        if ((Test-ItemNameMatch $desc $label) -or (Test-ItemNameMatch $desc $id)) {
            $hits += $it
        }
    }
    if ($hits.Count -ge 1) {
        $pick = $hits[0]
        if ($hits.Count -gt 1) {
            $bestLen = 99999
            foreach ($it in $hits) {
                $label = Normalize-ItemName (Get-SageItemLabel $it)
                $n = $label.Length
                if ($n -gt 0 -and $n -lt $bestLen) {
                    $pick = $it
                    $bestLen = $n
                }
            }
        }
        $matchedId = [string](Get-SageProp $pick "ID")
        Write-Host ("[ITEM] MATCH nombre: " + $matchedId + " | " + (Get-SageItemLabel $pick))
        return $pick
    }
    Write-Host ("[ITEM] NO MATCH: codigo=" + $wantId + " | " + $desc)
    return $null
}

function Get-RefId($obj) {
    if ($null -eq $obj) { return "" }
    foreach ($p in @("ID", "Id", "AccountID", "Guid", "Code")) {
        $v = Get-SageProp $obj $p
        if ($v) {
            $s = [string]$v
            if ($s.Trim()) { return $s.Trim() }
        }
    }
    return ""
}

function Dump-SageMethods($obj, [string]$label) {
    if ($null -eq $obj) { return }
    try {
        $ms = $obj.GetType().GetMethods() | ForEach-Object {
            $ps = ($_.GetParameters() | ForEach-Object { $_.ParameterType.Name }) -join ","
            $_.Name + "(" + $ps + ")"
        } | Sort-Object -Unique
        Write-Host ("  " + $label + " methods: " + ($ms -join "; "))
    }
    catch {
        Write-Host ("  " + $label + " methods: (no se pudieron listar)")
    }
}

function Invoke-SageFactoryCreate($factory) {
    $item = Invoke-SageMethod $factory "Create"
    if ($null -ne $item) { return $item }
    try {
        foreach ($m in $factory.GetType().GetMethods()) {
            if ($m.Name -notlike "*Create*") { continue }
            $pars = $m.GetParameters()
            Write-Host ("  metodo factory: " + $m.Name + "(" + (($pars | ForEach-Object { $_.ParameterType.Name }) -join ",") + ")")
            if ($pars.Count -eq 1 -and $pars[0].ParameterType.IsEnum) {
                foreach ($v in [enum]::GetValues($pars[0].ParameterType)) {
                    try {
                        $created = $m.Invoke($factory, @($v))
                        if ($null -ne $created) {
                            Write-Host ("  Create(" + $v + ") OK")
                            return $created
                        }
                    }
                    catch {
                        $inner = $_.Exception
                        if ($inner.InnerException) { $inner = $inner.InnerException }
                        Write-Host ("  AVISO Create(" + $v + "): " + $inner.Message)
                    }
                }
            }
        }
    }
    catch { }
    return $null
}

function Xml-Escape([string]$s) {
    if (-not $s) { return "" }
    return (($s -replace "&", "&amp;") -replace "<", "&lt;" -replace ">", "&gt;" -replace '"', "&quot;")
}

function Get-SageGlAccountId($ref) {
    if ($null -eq $ref) { return "" }
    foreach ($p in @("ID", "Id", "AccountID", "AccountId", "Code", "Number")) {
        $v = Get-SageProp $ref $p
        if ($v) {
            $s = ([string]$v).Trim()
            if ($s -and $s -notmatch '^[0-9a-fA-F]{8}-') { return $s }
        }
    }
    try {
        $s = ([string]$ref).Trim()
        if ($s -and $s -notmatch '^[0-9a-fA-F]{8}-' -and $s -notmatch 'Sage\.|EntityReference|Key') { return $s }
    }
    catch { }
    return ""
}

function Load-PeachwInterop {
    if ($script:PeachwInteropLoaded) { return }
    $script:PeachwInteropLoaded = $true
    $hits = @()
    $roots = @(
        "C:\Program Files (x86)\Sage\Peachtree\API",
        "C:\Program Files (x86)\Sage\Peachtree",
        "C:\Program Files (x86)\Sage",
        "C:\Sage"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        try {
            $hits += @(Get-ChildItem -LiteralPath $root -Filter "Interop.PeachwServer.dll" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 3)
        }
        catch { }
        if ($hits.Count -gt 0) { break }
    }
    foreach ($f in $hits) {
        try {
            [Reflection.Assembly]::LoadFrom($f.FullName) | Out-Null
            Write-Host ("COM Interop cargado: " + $f.FullName)
            return
        }
        catch {
            Write-Host ("AVISO no se cargo Interop: " + $f.FullName)
        }
    }
}

function Find-PeachwEnum([string]$typeName) {
    foreach ($asm in [AppDomain]::CurrentDomain.GetAssemblies()) {
        foreach ($full in @("Interop.PeachwServer." + $typeName, $typeName)) {
            try {
                $t = $asm.GetType($full, $false)
                if ($t -and $t.IsEnum) { return $t }
            }
            catch { }
        }
        try {
            $t = $asm.GetExportedTypes() | Where-Object { $_.Name -eq $typeName -and $_.IsEnum } | Select-Object -First 1
            if ($t) { return $t }
        }
        catch { }
    }
    return $null
}

function Get-SageComApp {
    if ($script:SageComApp) { return $script:SageComApp }
    if ($script:SageComDenied) { return $null }
    Load-PeachwInterop
    foreach ($prog in @(
            "PeachtreeAccounting.Login",
            "PeachtreeAccounting.Login.31"
        )) {
        try {
            $login = New-Object -ComObject $prog
            if (-not $login) { continue }
            Write-Host ("PROBE COM login: " + $prog)
            $names = @("Peachtree Software", "Auto-Hub", "Sage 50")
            foreach ($nm in $names) {
                try {
                    $app = $login.GetApplication($nm, $appId)
                    if ($app) {
                        Write-Host ("PROBE COM GetApplication OK (" + $nm + ")")
                        $script:SageComApp = $app
                        return $app
                    }
                }
                catch {
                    $msg = $_.Exception.Message
                    if ($_.Exception.InnerException) { $msg = $_.Exception.InnerException.Message }
                    if ($msg -match "80070005|Access is denied") {
                        Write-Host "PROBE COM denegado (este App ID es del SDK, no de COM)."
                        $script:SageComDenied = $true
                        return $null
                    }
                    Write-Host ("PROBE COM GetApplication " + $nm + ": " + $msg)
                }
            }
        }
        catch {
            Write-Host ("PROBE COM " + $prog + ": " + $_.Exception.Message)
        }
    }
    Write-Host "PROBE COM no disponible con este Application ID."
    $script:SageComDenied = $true
    return $null
}

function Find-PeachwEnumValue([string]$typeName, [string]$nameMatch) {
    $t = Find-PeachwEnum $typeName
    if (-not $t) { return $null }
    foreach ($n in [enum]::GetNames($t)) {
        if ($n -match $nameMatch) {
            $v = [int][enum]::Parse($t, $n)
            Write-Host ("COM enum " + $typeName + "." + $n + " = " + $v)
            return $v
        }
    }
    return $null
}

function Find-PeachwInventoryObjId($app) {
    if ($null -ne $script:PeachwInvObjId) { return $script:PeachwInvObjId }
    Load-PeachwInterop
    $v = Find-PeachwEnumValue "PeachwIEObj" "InventoryItemsList"
    if ($null -eq $v) { $v = Find-PeachwEnumValue "PeachwIEObj" "InventoryItem" }
    if ($null -ne $v) {
        Write-Host ("PROBE COM inventario enum=" + $v)
        $script:PeachwInvObjId = $v
        return $v
    }
    Write-Host "PROBE COM inventario enum=17 (fallback Sage 50 US)"
    $script:PeachwInvObjId = 17
    return 17
}

function Add-PeachwInventoryImportFields($imp) {
    try { $imp.ClearImportFieldList() } catch { }
    $t = Find-PeachwEnum "PeachwIEObjInventoryItemsListField"
    $added = 0
    if ($t) {
        foreach ($n in [enum]::GetNames($t)) {
            $ok = $false
            if ($n -match "Field_ItemId$" -or $n -match "Field_ItemID$") { $ok = $true }
            elseif ($n -match "ItemDescription" -and $n -notmatch "Purchase") { $ok = $true }
            elseif ($n -match "Field_Class$" -or $n -match "ItemClass") { $ok = $true }
            elseif ($n -match "SalesAccountId$" -or $n -match "GLSales") { $ok = $true }
            if (-not $ok) { continue }
            $v = [int][enum]::Parse($t, $n)
            try { $imp.AddToImportFieldList([int16]$v); $added++ } catch {
                try { $imp.AddToImportFieldList($v); $added++ } catch { }
            }
            Write-Host ("PROBE COM campo import: " + $n + "=" + $v)
        }
    }
    if ($added -lt 3) {
        foreach ($v in @(0, 1, 2, 19)) {
            try { $imp.AddToImportFieldList([int16]$v); $added++ } catch {
                try { $imp.AddToImportFieldList($v) } catch { }
            }
        }
        Write-Host "PROBE COM campos import fallback 0,1,2,19"
    }
}

function Invoke-SageComImport($app, [int]$objId, [string]$file, [int]$fileType, [bool]$headers) {
    $imp = $app.CreateImporter([int]$objId)
    if (-not $imp) { throw "CreateImporter devolvio null" }
    Add-PeachwInventoryImportFields $imp
    if ($headers) {
        try { $imp.SetFileIncludesHeadersFlag(1) } catch {
            try { $imp.SetIncludesHeadersFlag(1) } catch {
                try { $imp.SetIncludesHeaders(1) } catch { }
            }
        }
    }
    try { $imp.SetFileType([int]$fileType) } catch { }
    $imp.SetFilename($file)
    $imp.Import()
}

function Import-SageInventoryItemCom([string]$id, [string]$desc, [string]$salesAcctId) {
    Write-Host ("PROBE COM import start id=" + $id)
    $app = Get-SageComApp
    if (-not $app) { return $false }
    $objId = Find-PeachwInventoryObjId $app
    if ($null -eq $objId) { return $false }

    $safeDesc = Clip-SageText $desc 30
    $stem = "ah-item-" + ($id -replace "[^A-Za-z0-9\-]", "_")
    $xmlType = Find-PeachwEnumValue "PeachwIEFileType" "XML"
    if ($null -eq $xmlType) { $xmlType = 1 }
    $csvType = Find-PeachwEnumValue "PeachwIEFileType" "CSV"
    if ($null -eq $csvType) { $csvType = 0 }
    $sales = if ($salesAcctId) { $salesAcctId } else { "4001" }
    $eid = Xml-Escape $id
    $edesc = Xml-Escape $safeDesc
    $esales = Xml-Escape $sales

    $xmlBodies = @(
        ("<?xml version=`"1.0`"?>`r`n<PAW_Items>`r`n  <PAW_Item>`r`n    <ID>" + $eid + "</ID>`r`n    <Description>" + $edesc + "</Description>`r`n    <Class>1</Class>`r`n    <Sales_Account_ID>" + $esales + "</Sales_Account_ID>`r`n  </PAW_Item>`r`n</PAW_Items>`r`n"),
        ("<?xml version=`"1.0`"?>`r`n<PAW_Items>`r`n  <PAW_Item>`r`n    <ID>" + $eid + "</ID>`r`n    <Description>" + $edesc + "</Description>`r`n    <Type>1</Type>`r`n    <SalesAccountID>" + $esales + "</SalesAccountID>`r`n  </PAW_Item>`r`n</PAW_Items>`r`n"),
        ("<?xml version=`"1.0`"?>`r`n<PAW_Items>`r`n  <PAW_Item>`r`n    <ItemID>" + $eid + "</ItemID>`r`n    <ItemDescription>" + $edesc + "</ItemDescription>`r`n    <ItemClass>1</ItemClass>`r`n    <SalesAccountID>" + $esales + "</SalesAccountID>`r`n  </PAW_Item>`r`n</PAW_Items>`r`n")
    )
    $xi = 0
    foreach ($xml in $xmlBodies) {
        $xi++
        $xmlPath = Join-Path $env:TEMP ($stem + "-" + $xi + ".xml")
        try {
            [IO.File]::WriteAllText($xmlPath, $xml)
            Invoke-SageComImport $app ([int]$objId) $xmlPath ([int]$xmlType) $false
            Write-Host ("COM import item OK (XML" + $xi + "): " + $id)
            return $true
        }
        catch {
            $msg = $_.Exception.Message
            if ($_.Exception.InnerException) { $msg = $_.Exception.InnerException.Message }
            Write-Host ("PROBE COM import XML" + $xi + ": " + $msg)
        }
        finally {
            if (Test-Path -LiteralPath $xmlPath) { Remove-Item -LiteralPath $xmlPath -Force -ErrorAction SilentlyContinue }
        }
    }

    foreach ($cls in @(1, 3)) {
        $csvPath = Join-Path $env:TEMP ($stem + "-c" + $cls + ".csv")
        $hdr = '"Item ID","Item Description","Item Class","Sales Account ID"'
        $row = '"' + ($id -replace '"', '""') + '","' + ($safeDesc -replace '"', '""') + '",' + $cls + ',"' + ($sales -replace '"', '""') + '"'
        try {
            [IO.File]::WriteAllText($csvPath, $hdr + "`r`n" + $row + "`r`n")
            Invoke-SageComImport $app ([int]$objId) $csvPath ([int]$csvType) $true
            Write-Host ("COM import item OK (CSV class " + $cls + "): " + $id)
            return $true
        }
        catch {
            $msg = $_.Exception.Message
            if ($_.Exception.InnerException) { $msg = $_.Exception.InnerException.Message }
            Write-Host ("PROBE COM import CSV class " + $cls + ": " + $msg)
        }
        finally {
            if (Test-Path -LiteralPath $csvPath) { Remove-Item -LiteralPath $csvPath -Force -ErrorAction SilentlyContinue }
        }
    }
    return $false
}

function Ensure-SageUiWin32 {
    if ($script:SageUiCompileFailed) { return $false }
    if ("SageUiHost" -as [type]) { return $true }
    $code = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Threading;

public static class SageUiHost {
    public const uint WM_CLOSE = 0x0010;
    public const uint WM_COMMAND = 0x0111;
    public const uint WM_SYSCOMMAND = 0x0112;
    public const int SC_RESTORE = 0xF120;
    public const int SC_MAXIMIZE = 0xF030;
    public const uint SWP_NOSIZE = 0x0001;
    public const uint SWP_NOMOVE = 0x0002;
    public const uint SWP_SHOWWINDOW = 0x0040;
    public const uint WM_SETTEXT = 0x000C;
    public const uint BM_CLICK = 0x00F5;
    public const uint CB_SETCURSEL = 0x014E;
    public const uint KEYEVENTF_KEYUP = 0x0002;
    public const byte VK_MENU = 0x12;
    public const int SW_RESTORE = 9;
    public const int SW_SHOWNORMAL = 1;
    public const int SW_SHOWMAXIMIZED = 3;
    public const int CMD_INV = 30154;
    public const byte VK_M = 0x4D;
    public const byte VK_I = 0x49;
    public const byte VK_A = 0x41;
    public const uint MF_BYPOSITION = 0x00000400;
    public const int CTL_SAVE = 1;
    public const int CTL_NEW = 11;
    public const int CTL_ID = 401;
    public const int CTL_DESC = 402;
    public const int CTL_SALES = 510;
    public const int IDNO = 7;
    public const int IDOK = 1;

    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr h);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr h, int id);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "SendMessageW")]
    public static extern IntPtr SendMessageStr(IntPtr h, uint m, IntPtr w, string s);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool AllowSetForegroundWindow(int dwProcessId);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern bool OpenIcon(IntPtr h);
    [DllImport("user32.dll")] public static extern void SwitchToThisWindow(IntPtr h, bool f);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
    [DllImport("user32.dll")] public static extern IntPtr SetFocus(IntPtr h);
    [DllImport("user32.dll")] public static extern void keybd_event(byte b, byte s, uint f, UIntPtr e);
    [DllImport("user32.dll")] public static extern short VkKeyScan(char ch);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
    [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
    [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr hMenu);
    [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr hMenu, int nPos);
    [DllImport("user32.dll")] public static extern uint GetMenuState(IntPtr hMenu, uint uId, uint uFlags);
    [DllImport("user32.dll")] public static extern bool GetMenuItemRect(IntPtr hWnd, IntPtr hMenu, uint uItem, out RECT rc);
    [DllImport("user32.dll")] public static extern bool GetMenuBarInfo(IntPtr hwnd, uint idObject, uint idItem, ref MENUBARINFO pmbi);
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int n);
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetMenuString(IntPtr hMenu, uint uIDItem, StringBuilder lpString, int nMaxCount, uint uFlag);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

    [StructLayout(LayoutKind.Sequential)]
    public struct MENUBARINFO {
        public int cbSize;
        public RECT rcBar;
        public IntPtr hMenu;
        public IntPtr hwndMenu;
        public int flags;
    }

    static IntPtr _found;
    static IntPtr _childFound;
    static IntPtr _best;
    static int _bestArea;
    static bool _logHwnd;

    static void Trace(string fn, string paso, string detail) {
        Console.WriteLine("[TRACE] fn=" + fn + " paso=" + paso + " .. " + detail);
    }
    static void TraceFail(string fn, string paso, string detail) {
        Console.WriteLine("[TRACE] fn=" + fn + " paso=" + paso + " FAIL " + detail);
    }
    static string _wantClass;
    static string _wantTitle;
    static string _childNeedle;
    static int _closedJournals;
    static uint _wantPid;

    static bool MatchWin(IntPtr h, IntPtr l) {
        if (!IsWindowVisible(h)) return true;
        uint pid;
        GetWindowThreadProcessId(h, out pid);
        if (_wantPid != 0 && pid != _wantPid) return true;
        StringBuilder c = new StringBuilder(256);
        StringBuilder t = new StringBuilder(512);
        GetClassName(h, c, 256);
        GetWindowText(h, t, 512);
        string cs = c.ToString();
        string ts = t.ToString();
        if (_wantClass != null && cs == _wantClass) { _found = h; return false; }
        if (_wantTitle != null && ts.IndexOf(_wantTitle, StringComparison.OrdinalIgnoreCase) >= 0) {
            _found = h;
            return false;
        }
        return true;
    }

    static IntPtr FindVisible(string cls, string title, uint pid) {
        _found = IntPtr.Zero;
        _wantClass = cls;
        _wantTitle = title;
        _wantPid = pid;
        EnumWindows(MatchWin, IntPtr.Zero);
        return _found;
    }

    public static IntPtr FindPeachwMain() {
        _best = IntPtr.Zero;
        _bestArea = 0;
        EnumWindows(MatchBestSage, IntPtr.Zero);
        if (_best != IntPtr.Zero) return _best;
        IntPtr h = FindVisible("PEACHW", null, 0);
        if (h != IntPtr.Zero) return h;
        return FindVisible(null, "Sage 50", 0);
    }

    static bool MatchBestSage(IntPtr h, IntPtr l) {
        if (!IsWindowVisible(h)) return true;
        StringBuilder c = new StringBuilder(256);
        StringBuilder t = new StringBuilder(512);
        GetClassName(h, c, 256);
        GetWindowText(h, t, 512);
        string cs = c.ToString();
        string ts = t.ToString();
        bool isSage = cs == "PEACHW"
            || ts.IndexOf("Sage 50", StringComparison.OrdinalIgnoreCase) >= 0
            || ts.IndexOf("Peachtree", StringComparison.OrdinalIgnoreCase) >= 0;
        if (!isSage) return true;
        RECT r;
        GetWindowRect(h, out r);
        int area = Math.Max(0, r.Right - r.Left) * Math.Max(0, r.Bottom - r.Top);
        if (IsIconic(h)) area = Math.Max(area, 1);
        if (_logHwnd)
            Console.WriteLine("UI Win32: sagehwnd class=" + cs + " title=[" + ts + "] area=" + area + " iconic=" + (IsIconic(h) ? "1" : "0"));
        if (area > _bestArea) { _bestArea = area; _best = h; }
        return true;
    }

    static IntPtr _childClassFound;
    static string _wantChildClass;

    static bool MatchChildClass(IntPtr h, IntPtr l) {
        StringBuilder c = new StringBuilder(256);
        GetClassName(h, c, 256);
        if (_wantChildClass != null && c.ToString() == _wantChildClass) {
            _childClassFound = h;
            return false;
        }
        return true;
    }

    static IntPtr FindChildClass(IntPtr parent, string cls) {
        if (parent == IntPtr.Zero) return IntPtr.Zero;
        _childClassFound = IntPtr.Zero;
        _wantChildClass = cls;
        EnumChildWindows(parent, MatchChildClass, IntPtr.Zero);
        return _childClassFound;
    }

    static bool TitleLooksInventory(string ts) {
        if (string.IsNullOrEmpty(ts)) return false;
        string u = ts.ToUpperInvariant();
        if (u.IndexOf("MAINTAIN INVENTORY") >= 0) return true;
        if (u.IndexOf("INVENTORY ITEMS") >= 0) return true;
        if (u.IndexOf("ARTICULO") >= 0 && u.IndexOf("INVENT") >= 0) return true;
        if (u.IndexOf("ARTÍCULO") >= 0 && u.IndexOf("INVENT") >= 0) return true;
        return false;
    }

    static IntPtr _invChild;
    static bool MatchInvChild(IntPtr h, IntPtr l) {
        StringBuilder c = new StringBuilder(256);
        StringBuilder t = new StringBuilder(512);
        GetClassName(h, c, 256);
        GetWindowText(h, t, 512);
        if (c.ToString() == "LINEITEM" || TitleLooksInventory(t.ToString())) {
            _invChild = h;
            return false;
        }
        return true;
    }

    public static IntPtr FindInventory() {
        IntPtr h = FindVisible("LINEITEM", null, 0);
        if (h != IntPtr.Zero) return h;
        string[] titles = {
            "Maintain Inventory Items",
            "Inventory Items",
            "Artículos de inventario",
            "Articulos de inventario",
            "Mantener artículos de inventario",
            "Mantener articulos de inventario"
        };
        int i;
        for (i = 0; i < titles.Length; i++) {
            h = FindVisible(null, titles[i], 0);
            if (h != IntPtr.Zero) return h;
        }
        IntPtr main = FindPeachwMain();
        if (main != IntPtr.Zero) {
            h = FindChildClass(main, "LINEITEM");
            if (h != IntPtr.Zero) return h;
            _invChild = IntPtr.Zero;
            EnumChildWindows(main, MatchInvChild, IntPtr.Zero);
            if (_invChild != IntPtr.Zero) return _invChild;
        }
        return IntPtr.Zero;
    }

    public static void DumpPidWindows(uint pid) {
        _wantPid = pid;
        Console.WriteLine("UI Win32: ventanas peachw pid=" + pid);
        EnumWindows(LogSageWin, IntPtr.Zero);
    }

    static bool LogChildWin(IntPtr h, IntPtr l) {
        StringBuilder c = new StringBuilder(256);
        StringBuilder t = new StringBuilder(512);
        GetClassName(h, c, 256);
        GetWindowText(h, t, 512);
        string ts = t.ToString();
        if (c.ToString() == "Internet Explorer_Hidden" && ts.Length == 0) return true;
        Console.WriteLine("UI Win32:   child class=" + c.ToString() + " title=[" + ts + "] vis=" + (IsWindowVisible(h) ? "1" : "0"));
        return true;
    }

    static bool LogSageWin(IntPtr h, IntPtr l) {
        uint pid;
        GetWindowThreadProcessId(h, out pid);
        if (pid != _wantPid) return true;
        StringBuilder c = new StringBuilder(256);
        StringBuilder t = new StringBuilder(512);
        GetClassName(h, c, 256);
        GetWindowText(h, t, 512);
        RECT r;
        GetWindowRect(h, out r);
        int area = Math.Max(0, r.Right - r.Left) * Math.Max(0, r.Bottom - r.Top);
        Console.WriteLine("UI Win32: hwnd class=" + c.ToString() + " title=[" + t.ToString() + "] vis=" + (IsWindowVisible(h) ? "1" : "0") + " iconic=" + (IsIconic(h) ? "1" : "0") + " area=" + area);
        EnumChildWindows(h, LogChildWin, IntPtr.Zero);
        return true;
    }

    static uint PidOf(IntPtr h) {
        uint pid;
        GetWindowThreadProcessId(h, out pid);
        return pid;
    }

    static bool LooksLikeJournal(string cs, string ts) {
        if (cs == "PEACHW" || cs == "LINEITEM") return false;
        if (cs == "SAL_JRNL" || cs == "PUR_JRNL") return true;
        if (string.IsNullOrEmpty(ts)) return false;
        string u = ts.ToUpperInvariant();
        if (u.IndexOf("SALES/INVOICING") >= 0) return true;
        if (u.IndexOf("SALES / INVOICING") >= 0) return true;
        if (u.IndexOf("PURCHASES/") >= 0) return true;
        return false;
    }

    static bool CloseJournalWin(IntPtr h, IntPtr l) {
        uint pid;
        GetWindowThreadProcessId(h, out pid);
        if (pid != _wantPid) return true;
        StringBuilder c = new StringBuilder(256);
        StringBuilder t = new StringBuilder(512);
        GetClassName(h, c, 256);
        GetWindowText(h, t, 512);
        string cs = c.ToString();
        string ts = t.ToString();
        if (!LooksLikeJournal(cs, ts)) return true;
        Console.WriteLine("UI Win32: cierro journal class=" + cs + " title=[" + ts + "] iconic=" + (IsIconic(h) ? "1" : "0"));
        if (IsIconic(h)) {
            OpenIcon(h);
            Thread.Sleep(250);
        }
        Foreground(h);
        Thread.Sleep(120);
        if (!ClickChild(h, "Close")) {
            IntPtr closeBtn = GetDlgItem(h, 2);
            if (closeBtn != IntPtr.Zero) ClickHwnd(closeBtn);
        }
        PostMessage(h, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
        _closedJournals++;
        return true;
    }

    static void ClickRect(RECT r) {
        int x = (r.Left + r.Right) / 2;
        int y = (r.Top + r.Bottom) / 2;
        if (x == 0 && y == 0) return;
        SetCursorPos(x, y);
        Thread.Sleep(50);
        mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);
        Thread.Sleep(40);
        mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
        Thread.Sleep(120);
    }

    static int _hiddenForms;
    static IntPtr _tabFound;
    static int _postCmd;

    static bool HideFormsChild(IntPtr h, IntPtr l) {
        if (!IsWindowVisible(h)) return true;
        StringBuilder c = new StringBuilder(256);
        StringBuilder t = new StringBuilder(512);
        GetClassName(h, c, 256);
        GetWindowText(h, t, 512);
        string cs = c.ToString();
        if (cs.IndexOf("WindowsForms10") < 0) return true;
        RECT r;
        GetWindowRect(h, out r);
        int area = Math.Max(0, r.Right - r.Left) * Math.Max(0, r.Bottom - r.Top);
        string ts = t.ToString();
        string u = ts.ToUpperInvariant();
        bool overlay = area > 40000
            || u.IndexOf("CUSTOMERS") >= 0
            || u.IndexOf("MODULEMANAGER") >= 0
            || u.IndexOf("SAGE ADVISOR") >= 0
            || u.IndexOf("SHORTCUT") >= 0
            || cs.IndexOf("SysTabControl32") >= 0;
        if (!overlay) return true;
        Console.WriteLine("UI Win32: oculto overlay class=" + cs + " title=[" + ts + "] area=" + area);
        ShowWindow(h, 0);
        _hiddenForms++;
        return true;
    }

    public static int HideWinFormsOverlay(IntPtr main) {
        _hiddenForms = 0;
        if (main == IntPtr.Zero) return 0;
        EnumChildWindows(main, HideFormsChild, IntPtr.Zero);
        Trace("HideWinFormsOverlay", "done", "hidden=" + _hiddenForms);
        return _hiddenForms;
    }

    static bool MatchTabClass(IntPtr h, IntPtr l) {
        StringBuilder c = new StringBuilder(256);
        GetClassName(h, c, 256);
        if (c.ToString().IndexOf("SysTabControl32") >= 0) {
            _tabFound = h;
            return false;
        }
        return true;
    }

    static bool ClickOverlayInventory(IntPtr main) {
        if (ClickChildContains(main, "Inventory Items")) return true;
        if (ClickChildContains(main, "Inventory Item")) return true;
        _tabFound = IntPtr.Zero;
        EnumChildWindows(main, MatchTabClass, IntPtr.Zero);
        if (_tabFound == IntPtr.Zero) {
            Trace("ClickOverlayInventory", "no-tab", "SysTabControl32=0");
            return false;
        }
        const uint TCM_GETITEMCOUNT = 0x1304;
        int n = SendMessage(_tabFound, TCM_GETITEMCOUNT, IntPtr.Zero, IntPtr.Zero).ToInt32();
        RECT r;
        GetWindowRect(_tabFound, out r);
        Trace("ClickOverlayInventory", "tabs", "count=" + n + " rect=" + r.Left + "," + r.Top);
        if (n < 1) n = 8;
        int w = Math.Max(20, (r.Right - r.Left) / n);
        int i;
        for (i = 0; i < n; i++) {
            RECT click;
            click.Left = r.Left + (w * i) + 8;
            click.Right = click.Left + 12;
            click.Top = r.Top + 4;
            click.Bottom = r.Top + 18;
            ClickRect(click);
            Thread.Sleep(350);
            if (ClickChildContains(main, "Inventory Items")) return true;
            if (FindInventory() != IntPtr.Zero) return true;
        }
        return false;
    }

    static bool RectLooksValid(RECT r) {
        return r.Right > r.Left && r.Bottom > r.Top;
    }

    static bool RectForMenuBarItem(IntPtr hwnd, IntPtr menu, int index, out RECT r) {
        r = new RECT();
        MENUBARINFO mbi = new MENUBARINFO();
        mbi.cbSize = Marshal.SizeOf(typeof(MENUBARINFO));
        if (GetMenuBarInfo(hwnd, 0xFFFFFFFD, (uint)(index + 1), ref mbi) && RectLooksValid(mbi.rcBar)) {
            r = mbi.rcBar;
            return true;
        }
        if (GetMenuItemRect(hwnd, menu, (uint)index, out r) && RectLooksValid(r)) return true;
        RECT wr;
        GetWindowRect(hwnd, out wr);
        int cap = GetSystemMetrics(4);
        int frame = GetSystemMetrics(32);
        int menuH = GetSystemMetrics(15);
        if (menuH < 8) menuH = 20;
        int y = wr.Top + frame + cap + (menuH / 2);
        int x = wr.Left + frame + 16 + (index * 58) + 24;
        r.Left = x - 10;
        r.Right = x + 10;
        r.Top = y - 4;
        r.Bottom = y + 4;
        Trace("RectForMenuBarItem", "estimado", "index=" + index + " x=" + x + " y=" + y);
        return RectLooksValid(r);
    }

    static bool PostCmdChild(IntPtr h, IntPtr l) {
        StringBuilder c = new StringBuilder(256);
        GetClassName(h, c, 256);
        string cs = c.ToString();
        if (cs.StartsWith("Afx:") || cs == "MDIClient") {
            Console.WriteLine("UI Win32: WM_COMMAND " + _postCmd + " -> child " + cs);
            PostMessage(h, WM_COMMAND, (IntPtr)_postCmd, IntPtr.Zero);
        }
        return true;
    }

    static bool PostCommandToMdi(IntPtr main, int cmd) {
        _postCmd = cmd;
        PostMessage(main, WM_COMMAND, (IntPtr)cmd, IntPtr.Zero);
        EnumChildWindows(main, PostCmdChild, IntPtr.Zero);
        return true;
    }

    public static bool ClickInventoryMenu(IntPtr main) {
        IntPtr menu = GetMenu(main);
        if (menu == IntPtr.Zero) {
            TraceFail("ClickInventoryMenu", "GetMenu", "menu=0");
            return false;
        }
        IntPtr console = GetConsoleWindow();
        if (console != IntPtr.Zero) ShowWindow(console, 0);
        Foreground(main);
        Thread.Sleep(200);
        int tops = GetMenuItemCount(menu);
        int i;
        int j;
        for (i = 0; i < tops; i++) {
            string top = MenuText(menu, i);
            string u = top.ToUpperInvariant();
            if (u.IndexOf("MAINTAIN") < 0 && u.IndexOf("MANTENIM") < 0) continue;
            RECT r;
            bool got = RectForMenuBarItem(main, menu, i, out r);
            Trace("ClickInventoryMenu", "top", "[" + top + "] i=" + i + " gotRect=" + (got ? "1" : "0") + " rect=" + r.Left + "," + r.Top + "," + r.Right + "," + r.Bottom);
            Console.WriteLine("UI Win32: click menu [" + top + "] rect=" + r.Left + "," + r.Top);
            if (!got) {
                TraceFail("ClickInventoryMenu", "GetMenuItemRect", "Maintain i=" + i + " sin rect");
                continue;
            }
            ClickRect(r);
            Thread.Sleep(450);
            IntPtr sub = GetSubMenu(menu, i);
            if (sub == IntPtr.Zero) continue;
            int n = GetMenuItemCount(sub);
            int invPos = -1;
            for (j = 0; j < n; j++) {
                string item = MenuText(sub, j);
                if (!IsInvMenuItem(item)) continue;
                invPos = j;
                RECT r2;
                uint id = GetMenuItemID(sub, j);
                bool got2 = GetMenuItemRect(main, sub, (uint)j, out r2) && RectLooksValid(r2);
                if (!got2 && id != 0 && id != 0xFFFFFFFF)
                    got2 = GetMenuItemRect(main, sub, id, out r2) && RectLooksValid(r2);
                Trace("ClickInventoryMenu", "item", "[" + item + "] j=" + j + " gotRect=" + (got2 ? "1" : "0") + " rect=" + r2.Left + "," + r2.Top);
                if (got2) {
                    Console.WriteLine("UI Win32: click item [" + item + "] rect=" + r2.Left + "," + r2.Top);
                    ClickRect(r2);
                    Thread.Sleep(400);
                    return true;
                }
            }
            if (invPos >= 0) {
                Trace("ClickInventoryMenu", "flechas", "Inventory Items pos=" + invPos);
                int k;
                for (k = 0; k <= invPos; k++) { KeyDown(0x28); KeyUp(0x28); Thread.Sleep(50); }
                KeyDown(0x0D);
                KeyUp(0x0D);
                Thread.Sleep(400);
                return true;
            }
        }
        TraceFail("ClickInventoryMenu", "no-menu", "no se encontro Maintain/Inventory Items");
        return false;
    }

    public static int CloseJournalWindows(uint pid) {
        _wantPid = pid;
        _closedJournals = 0;
        EnumWindows(CloseJournalWin, IntPtr.Zero);
        Console.WriteLine("[TRACE] fn=CloseJournalWindows paso=enum pid=" + pid + " cerrados=" + _closedJournals);
        return _closedJournals;
    }

    public static bool ForceRestore(IntPtr h) {
        if (h == IntPtr.Zero) return false;
        try { AllowSetForegroundWindow(-1); } catch { }
        uint pid;
        uint tid = GetWindowThreadProcessId(h, out pid);
        uint mine = GetCurrentThreadId();
        AttachThreadInput(mine, tid, true);
        OpenIcon(h);
        PostMessage(h, WM_SYSCOMMAND, (IntPtr)SC_RESTORE, IntPtr.Zero);
        SendMessage(h, WM_SYSCOMMAND, (IntPtr)SC_RESTORE, IntPtr.Zero);
        ShowWindowAsync(h, SW_RESTORE);
        ShowWindow(h, SW_RESTORE);
        ShowWindow(h, SW_SHOWNORMAL);
        ShowWindowAsync(h, SW_SHOWMAXIMIZED);
        ShowWindow(h, SW_SHOWMAXIMIZED);
        PostMessage(h, WM_SYSCOMMAND, (IntPtr)SC_MAXIMIZE, IntPtr.Zero);
        SetWindowPos(h, new IntPtr(-1), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
        SetWindowPos(h, new IntPtr(-2), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
        BringWindowToTop(h);
        SwitchToThisWindow(h, true);
        SetForegroundWindow(h);
        AttachThreadInput(mine, tid, false);
        int i;
        for (i = 0; i < 25; i++) {
            Thread.Sleep(120);
            if (!IsIconic(h)) {
                RECT r;
                GetWindowRect(h, out r);
                int area = Math.Max(0, r.Right - r.Left) * Math.Max(0, r.Bottom - r.Top);
                Console.WriteLine("UI Win32: Sage restaurado area=" + area + " iconic=0");
                return true;
            }
        }
        Console.WriteLine("UI Win32: Sage SIGUE minimizado (iconic=1). Restore no hizo efecto.");
        return false;
    }

    public static void Foreground(IntPtr h) {
        if (h == IntPtr.Zero) return;
        if (IsIconic(h) || WindowArea(h) < 80000) {
            Console.WriteLine("UI Win32: Sage chico/minimizado area=" + WindowArea(h) + " -> restore");
            ForceRestore(h);
            return;
        }
        try { AllowSetForegroundWindow(-1); } catch { }
        uint pid;
        uint tid = GetWindowThreadProcessId(h, out pid);
        uint mine = GetCurrentThreadId();
        keybd_event(VK_MENU, 0, 0, UIntPtr.Zero);
        AttachThreadInput(mine, tid, true);
        ShowWindow(h, SW_RESTORE);
        BringWindowToTop(h);
        SetForegroundWindow(h);
        AttachThreadInput(mine, tid, false);
        keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    }

    static int WindowArea(IntPtr h) {
        RECT r;
        GetWindowRect(h, out r);
        return Math.Max(0, r.Right - r.Left) * Math.Max(0, r.Bottom - r.Top);
    }

    static void SendAltKey(byte vk) {
        KeyDown(VK_MENU);
        Thread.Sleep(40);
        KeyDown(vk);
        Thread.Sleep(40);
        KeyUp(vk);
        Thread.Sleep(40);
        KeyUp(VK_MENU);
        Thread.Sleep(200);
    }

    static void ClickHwnd(IntPtr h) {
        if (h == IntPtr.Zero) return;
        RECT r;
        GetWindowRect(h, out r);
        int x = (r.Left + r.Right) / 2;
        int y = (r.Top + r.Bottom) / 2;
        SetCursorPos(x, y);
        Thread.Sleep(40);
        mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);
        Thread.Sleep(40);
        mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
        Thread.Sleep(80);
    }

    static void KeyDown(byte vk) { keybd_event(vk, 0, 0, UIntPtr.Zero); }
    static void KeyUp(byte vk) { keybd_event(vk, 0, KEYEVENTF_KEYUP, UIntPtr.Zero); }

    static void TypeString(string s) {
        if (string.IsNullOrEmpty(s)) return;
        foreach (char ch in s) {
            short scan = VkKeyScan(ch);
            if (scan == -1) continue;
            byte vk = (byte)(scan & 0xFF);
            bool shift = (scan & 0x100) != 0;
            if (shift) KeyDown(0x10);
            KeyDown(vk);
            KeyUp(vk);
            if (shift) KeyUp(0x10);
            Thread.Sleep(15);
        }
    }

    static void SelectAllType(string s) {
        KeyDown(0x11);
        KeyDown(0x41);
        KeyUp(0x41);
        KeyUp(0x11);
        Thread.Sleep(40);
        TypeString(s);
    }

    static bool MatchChild(IntPtr h, IntPtr l) {
        if (!IsWindowVisible(h)) return true;
        StringBuilder t = new StringBuilder(128);
        GetWindowText(h, t, 128);
        string ts = t.ToString().Replace("&", "");
        if (ts.Equals(_childNeedle, StringComparison.OrdinalIgnoreCase)) {
            _childFound = h;
            return false;
        }
        return true;
    }

    static bool LogChild(IntPtr h, IntPtr l) {
        StringBuilder t = new StringBuilder(256);
        GetWindowText(h, t, 256);
        if (t.Length > 0) Console.WriteLine("UI Win32: dlgchild [" + t.ToString() + "]");
        return true;
    }

    static bool ClickChild(IntPtr parent, string text) {
        _childFound = IntPtr.Zero;
        _childNeedle = text;
        EnumChildWindows(parent, MatchChild, IntPtr.Zero);
        if (_childFound == IntPtr.Zero) return false;
        Console.WriteLine("UI Win32: click boton [" + text + "]");
        ClickHwnd(_childFound);
        PostMessage(_childFound, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
        return true;
    }

    public static void DismissDialogs(uint peachwPid, bool saveRecord) {
        for (int n = 0; n < 6; n++) {
            IntPtr dlg = FindVisible("#32770", null, peachwPid);
            if (dlg == IntPtr.Zero) return;
            StringBuilder t = new StringBuilder(512);
            GetWindowText(dlg, t, 512);
            Console.WriteLine("UI Win32: dialogo [" + t.ToString() + "] save=" + saveRecord);
            EnumChildWindows(dlg, LogChild, IntPtr.Zero);
            Foreground(dlg);
            Thread.Sleep(80);
            bool clicked = false;
            if (saveRecord) {
                clicked = ClickChild(dlg, "Yes") || ClickChild(dlg, "Si") || ClickChild(dlg, "OK");
                if (!clicked) {
                    IntPtr b = GetDlgItem(dlg, 6);
                    if (b != IntPtr.Zero) { ClickHwnd(b); clicked = true; }
                }
            } else {
                clicked = ClickChild(dlg, "No") || ClickChild(dlg, "Cancel") || ClickChild(dlg, "Close") || ClickChild(dlg, "OK");
                if (!clicked) {
                    IntPtr b = GetDlgItem(dlg, IDNO);
                    if (b != IntPtr.Zero) { ClickHwnd(b); clicked = true; }
                }
            }
            if (!clicked) {
                IntPtr ok = GetDlgItem(dlg, IDOK);
                if (ok != IntPtr.Zero) ClickHwnd(ok);
            }
            Thread.Sleep(300);
        }
    }

    static bool ClickChildContains(IntPtr parent, string text) {
        _childFound = IntPtr.Zero;
        _childNeedle = text;
        EnumChildWindows(parent, MatchChildContains, IntPtr.Zero);
        if (_childFound == IntPtr.Zero) return false;
        Console.WriteLine("UI Win32: click [" + text + "]");
        ClickHwnd(_childFound);
        return true;
    }

    static bool MatchChildContains(IntPtr h, IntPtr l) {
        if (!IsWindowVisible(h)) return true;
        StringBuilder t = new StringBuilder(128);
        GetWindowText(h, t, 128);
        string ts = t.ToString().Replace("&", "");
        if (ts.IndexOf(_childNeedle, StringComparison.OrdinalIgnoreCase) >= 0) {
            _childFound = h;
            return false;
        }
        return true;
    }

    static void FillItemClass(IntPtr inv) {
        ClickChildContains(inv, "defaults");
        IntPtr combo = GetDlgItem(inv, 409);
        if (combo == IntPtr.Zero) return;
        Console.WriteLine("UI Win32: Item Class combo -> Non-stock (flechas)");
        ClickHwnd(combo);
        Thread.Sleep(120);
        KeyDown(0x12);
        KeyDown(0x28);
        KeyUp(0x28);
        KeyUp(0x12);
        Thread.Sleep(150);
        int i;
        for (i = 0; i < 20; i++) { KeyDown(0x26); KeyUp(0x26); Thread.Sleep(20); }
        Thread.Sleep(80);
        for (i = 0; i < 3; i++) { KeyDown(0x28); KeyUp(0x28); Thread.Sleep(40); }
        KeyDown(0x0D);
        KeyUp(0x0D);
        Thread.Sleep(150);
        KeyDown(0x09);
        KeyUp(0x09);
    }

    static void TypeAccount(IntPtr inv, int ctlId, string acct) {
        IntPtr h = GetDlgItem(inv, ctlId);
        if (h == IntPtr.Zero || string.IsNullOrEmpty(acct)) return;
        Console.WriteLine("UI Win32: GL ctl=" + ctlId + " -> " + acct);
        ClickHwnd(h);
        Thread.Sleep(80);
        SelectAllType(acct);
        KeyDown(0x09);
        KeyUp(0x09);
        Thread.Sleep(250);
    }

    static string MenuText(IntPtr menu, int pos) {
        StringBuilder s = new StringBuilder(256);
        GetMenuString(menu, (uint)pos, s, 256, MF_BYPOSITION);
        return s.ToString().Replace("&", "").Trim();
    }

    static bool IsInvMenuItem(string t) {
        if (string.IsNullOrEmpty(t)) return false;
        string u = t.ToUpperInvariant();
        if (u.IndexOf("INVENTORY ITEM") >= 0) return true;
        if (u.IndexOf("ARTICULO") >= 0 && u.IndexOf("INVENT") >= 0) return true;
        if (u.IndexOf("ARTÍCULO") >= 0) return true;
        if (u == "INVENTORY ITEMS" || u == "INVENTORY") return true;
        if (u.IndexOf("ITEMS DE INVENTARIO") >= 0) return true;
        return false;
    }

    public static int FindInventoryMenuCmd(IntPtr main) {
        IntPtr menu = GetMenu(main);
        Console.WriteLine("UI Win32: GetMenu=" + menu.ToInt64());
        if (menu == IntPtr.Zero) return 0;
        int tops = GetMenuItemCount(menu);
        Console.WriteLine("UI Win32: menus top=" + tops);
        int i;
        int j;
        for (i = 0; i < tops; i++) {
            string top = MenuText(menu, i);
            IntPtr sub = GetSubMenu(menu, i);
            Console.WriteLine("UI Win32: menu[" + i + "]=[" + top + "]");
            if (sub == IntPtr.Zero) continue;
            int n = GetMenuItemCount(sub);
            for (j = 0; j < n; j++) {
                string item = MenuText(sub, j);
                uint id = GetMenuItemID(sub, j);
                if (!string.IsNullOrEmpty(item))
                    Console.WriteLine("UI Win32:   id=" + id + " [" + item + "]");
                if (id == 0 || id == 0xFFFFFFFF) continue;
                if (IsInvMenuItem(item)) {
                    Console.WriteLine("UI Win32: comando inventario=" + id + " (" + item + ")");
                    return (int)id;
                }
            }
        }
        for (i = 0; i < tops; i++) {
            string top = MenuText(menu, i).ToUpperInvariant();
            if (top.IndexOf("MAINTAIN") < 0 && top.IndexOf("MANTENIM") < 0) continue;
            IntPtr sub = GetSubMenu(menu, i);
            if (sub == IntPtr.Zero) continue;
            int n = GetMenuItemCount(sub);
            for (j = 0; j < n; j++) {
                string item = MenuText(sub, j);
                uint id = GetMenuItemID(sub, j);
                if (id == 0 || id == 0xFFFFFFFF) continue;
                string u = item.ToUpperInvariant();
                if (u.IndexOf("INVENT") >= 0 || u.IndexOf("ARTIC") >= 0) {
                    Console.WriteLine("UI Win32: comando inventario(Maintain)=" + id + " (" + item + ")");
                    return (int)id;
                }
            }
        }
        return 0;
    }

    static bool WaitInventory(uint pid, string via, int tries) {
        int i;
        for (i = 0; i < tries; i++) {
            Thread.Sleep(250);
            DismissDialogs(pid, false);
            IntPtr inv = FindInventory();
            if (inv != IntPtr.Zero) {
                Trace("WaitInventory", "found", "via=" + via + " try=" + (i + 1) + "/" + tries + " hwnd=" + inv.ToInt64());
                return true;
            }
        }
        TraceFail("WaitInventory", "timeout", "via=" + via + " tries=" + tries + " LINEITEM=0");
        return false;
    }

    public static bool OpenInventoryWindow() {
        _logHwnd = true;
        IntPtr main = FindPeachwMain();
        _logHwnd = false;
        if (main == IntPtr.Zero) {
            TraceFail("OpenInventoryWindow", "1-FindPeachwMain", "hwnd=0 (no PEACHW)");
            Console.WriteLine("UI Win32: no hay ventana Sage (PEACHW).");
            return false;
        }
        uint pid = PidOf(main);
        Trace("OpenInventoryWindow", "1-FindPeachwMain", "hwnd=" + main.ToInt64() + " pid=" + pid + " area=" + WindowArea(main) + " iconic=" + (IsIconic(main) ? "1" : "0"));
        IntPtr console = GetConsoleWindow();
        if (console != IntPtr.Zero) ShowWindow(console, 0);
        Foreground(main);
        Thread.Sleep(400);
        if (IsIconic(main)) {
            TraceFail("OpenInventoryWindow", "2-iconic", "Sage sigue minimizado pid=" + pid);
            Console.WriteLine("UI Win32: no se puede abrir Maintain Inventory con Sage minimizado. Restaura la ventana de Sage (no la dejes en la barra).");
            DumpPidWindows(pid);
            return false;
        }
        Console.WriteLine("UI Win32: click overlay Inventory Items / tabs");
        Trace("OpenInventoryWindow", "2a-ClickOverlay", "WinForms visible");
        if (ClickOverlayInventory(main) && WaitInventory(pid, "ClickOverlay", 8)) return true;
        int hidden = HideWinFormsOverlay(main);
        Trace("OpenInventoryWindow", "2b-HideWinForms", "hidden=" + hidden);
        Thread.Sleep(350);
        Foreground(main);
        Thread.Sleep(200);
        int closed = CloseJournalWindows(pid);
        Trace("OpenInventoryWindow", "3-CloseJournalWindows", "cerrados=" + closed);
        Thread.Sleep(400);
        DismissDialogs(pid, false);
        Thread.Sleep(200);
        if (FindInventory() != IntPtr.Zero) {
            Trace("OpenInventoryWindow", "4-alreadyOpen", "LINEITEM ya estaba abierta");
            return true;
        }
        int cmd = FindInventoryMenuCmd(main);
        if (cmd == 0) {
            Console.WriteLine("UI Win32: menu sin Inventory Items; fallback 30154");
            cmd = CMD_INV;
        }
        Trace("OpenInventoryWindow", "5-FindInventoryMenuCmd", "cmd=" + cmd);
        IntPtr menu = GetMenu(main);
        if (menu != IntPtr.Zero) {
            uint st = GetMenuState(menu, (uint)cmd, 0);
            Console.WriteLine("UI Win32: menu cmd=" + cmd + " state=" + st + " grayed=" + ((st & 3) != 0 && st != 0xFFFFFFFF ? "1" : "0"));
            Trace("OpenInventoryWindow", "6-GetMenuState", "cmd=" + cmd + " state=" + st + " grayed=" + ((st & 3) != 0 && st != 0xFFFFFFFF ? "1" : "0"));
            if ((st & 3) != 0 && st != 0xFFFFFFFF) {
                Console.WriteLine("UI Win32: Inventory Items esta gris. Reintento cerrar journals.");
                CloseJournalWindows(pid);
                Thread.Sleep(500);
                DismissDialogs(pid, false);
            }
        } else {
            Trace("OpenInventoryWindow", "6-GetMenuState", "GetMenu=0 (menu no accesible)");
        }
        Console.WriteLine("UI Win32: PostMessage WM_COMMAND " + cmd + " (frame+MDI)");
        Trace("OpenInventoryWindow", "7-PostCommandToMdi", "cmd=" + cmd);
        PostCommandToMdi(main, cmd);
        if (WaitInventory(pid, "PostCommandToMdi", 12)) return true;
        Console.WriteLine("UI Win32: SendMessage WM_COMMAND " + cmd);
        Trace("OpenInventoryWindow", "8-SendMessage", "cmd=" + cmd);
        SendMessage(main, WM_COMMAND, (IntPtr)cmd, IntPtr.Zero);
        if (WaitInventory(pid, "SendMessage", 8)) return true;
        Console.WriteLine("UI Win32: click Maintain / Inventory Items");
        Trace("OpenInventoryWindow", "9-ClickInventoryMenu", "click menu");
        bool clicked = ClickInventoryMenu(main);
        Trace("OpenInventoryWindow", "9-ClickInventoryMenu", "clicked=" + (clicked ? "1" : "0"));
        if (WaitInventory(pid, "ClickInventoryMenu", 16)) return true;
        Foreground(main);
        Thread.Sleep(200);
        Console.WriteLine("UI Win32: WM_SYSCOMMAND SC_KEYMENU m + i");
        Trace("OpenInventoryWindow", "10-SC_KEYMENU", "m+i");
        SendMessage(main, WM_SYSCOMMAND, (IntPtr)0xF100, (IntPtr)0x6D);
        Thread.Sleep(350);
        KeyDown(VK_I); KeyUp(VK_I);
        if (WaitInventory(pid, "SC_KEYMENU", 12)) return true;
        Console.WriteLine("UI Win32: Alt+M I (Maintain / Inventory)");
        Trace("OpenInventoryWindow", "11-Alt+M I", "teclado");
        SendAltKey(VK_M);
        KeyDown(VK_I); KeyUp(VK_I);
        if (WaitInventory(pid, "Alt+M I", 16)) return true;
        Console.WriteLine("UI Win32: Alt+A I");
        Trace("OpenInventoryWindow", "12-Alt+A I", "teclado");
        SendAltKey(VK_A);
        KeyDown(VK_I); KeyUp(VK_I);
        if (WaitInventory(pid, "Alt+A I", 12)) return true;
        DumpPidWindows(pid);
        TraceFail("OpenInventoryWindow", "13-noLINEITEM", "no LINEITEM tras 6 vias cmd=" + cmd + " pid=" + pid);
        Console.WriteLine("UI Win32: no se abrio Maintain Inventory Items. cmd=" + cmd);
        return false;
    }

    public static bool CreateInventoryItem(string id, string desc, string salesGl) {
        Trace("CreateInventoryItem", "0-start", "sku=" + id + " gl=" + salesGl);
        Console.WriteLine("UI Win32: abriendo Maintain Inventory Items...");
        if (!OpenInventoryWindow()) {
            TraceFail("CreateInventoryItem", "1-OpenInventoryWindow", "sku=" + id);
            return false;
        }
        IntPtr inv = FindInventory();
        if (inv == IntPtr.Zero) {
            TraceFail("CreateInventoryItem", "2-FindInventory", "sku=" + id + " hwnd=0");
            Console.WriteLine("UI Win32: no se abrio Maintain Inventory Items.");
            return false;
        }
        Trace("CreateInventoryItem", "2-FindInventory", "hwnd=" + inv.ToInt64() + " sku=" + id);
        Console.WriteLine("UI Win32: ventana LINEITEM abierta.");
        uint pid = PidOf(inv);
        Foreground(inv);
        Thread.Sleep(250);
        DismissDialogs(pid, false);
        IntPtr newBtn = GetDlgItem(inv, CTL_NEW);
        Trace("CreateInventoryItem", "3-New", "CTL_NEW=" + newBtn.ToInt64());
        ClickHwnd(newBtn);
        Thread.Sleep(400);
        DismissDialogs(pid, false);
        ClickHwnd(newBtn);
        Thread.Sleep(400);
        DismissDialogs(pid, false);
        IntPtr idCtl = GetDlgItem(inv, CTL_ID);
        IntPtr descCtl = GetDlgItem(inv, CTL_DESC);
        if (idCtl == IntPtr.Zero || descCtl == IntPtr.Zero) {
            TraceFail("CreateInventoryItem", "4-campos", "sku=" + id + " CTL_ID=" + idCtl.ToInt64() + " CTL_DESC=" + descCtl.ToInt64());
            Console.WriteLine("UI Win32: no se encontraron campos Item ID / Description.");
            return false;
        }
        Trace("CreateInventoryItem", "4-campos", "CTL_ID=" + idCtl.ToInt64() + " CTL_DESC=" + descCtl.ToInt64());
        Foreground(inv);
        ClickHwnd(idCtl);
        SetFocus(idCtl);
        Thread.Sleep(80);
        SelectAllType(id);
        KeyDown(0x09);
        KeyUp(0x09);
        Thread.Sleep(80);
        SelectAllType(desc);
        KeyDown(0x09);
        KeyUp(0x09);
        Thread.Sleep(80);
        FillItemClass(inv);
        TypeAccount(inv, 510, string.IsNullOrEmpty(salesGl) ? "4001" : salesGl);
        TypeAccount(inv, 514, "1110");
        TypeAccount(inv, 517, "5001");
        Thread.Sleep(300);
        IntPtr saveBtn = GetDlgItem(inv, CTL_SAVE);
        Trace("CreateInventoryItem", "5-Save", "CTL_SAVE=" + saveBtn.ToInt64() + " sku=" + id);
        ClickHwnd(saveBtn);
        Thread.Sleep(500);
        DismissDialogs(pid, true);
        Thread.Sleep(400);
        Console.WriteLine("UI Win32: Save enviado id=" + id);
        Trace("CreateInventoryItem", "6-done", "sku=" + id + " Save enviado");
        return true;
    }
}
'@
    try {
        Write-AhTrace -Fn "Ensure-SageUiWin32" -Paso "Add-Type" -Detail "compilando SageUiHost"
        Add-Type -TypeDefinition $code -Language CSharp -ErrorAction Stop
        Write-AhTrace -Fn "Ensure-SageUiWin32" -Paso "Add-Type" -Detail "SageUiHost listo" -Ok $true
        return $true
    }
    catch {
        $script:SageUiCompileFailed = $true
        $err = $_.Exception
        $full = [string]$err.Message
        $inner = $err
        while ($inner.InnerException) {
            $inner = $inner.InnerException
            $full += " | INNER: " + $inner.Message
        }
        if ($err.Errors) {
            foreach ($ce in @($err.Errors)) {
                $full += " | CS: " + [string]$ce
            }
        }
        if ($_.Exception.ErrorRecord) {
            $full += " | ERRREC: " + $_.Exception.ErrorRecord
        }
        Write-AhTrace -Fn "Ensure-SageUiWin32" -Paso "Add-Type" -Detail $full -Ok $false
        Write-Host ("AVISO Win32 UI no cargo: " + $full)
        Write-Host ("[TRACE] Add-Type Exception.ToString: " + $err.ToString())
        return $false
    }
}

function Ensure-UiaLoaded {
    if ($script:UiaReady) { return $true }
    try {
        [void][Reflection.Assembly]::LoadWithPartialName("UIAutomationClient")
        [void][Reflection.Assembly]::LoadWithPartialName("UIAutomationTypes")
        [void][Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
        $script:UiaReady = $true
        return $true
    }
    catch {
        Write-Host ("AVISO UI Automation no cargo: " + $_.Exception.Message)
        return $false
    }
}

function Get-SageMainElement {
    if (-not (Ensure-UiaLoaded)) { return $null }
    $procs = @(Get-Process | Where-Object {
            $_.MainWindowHandle -ne [IntPtr]::Zero -and
            ($_.ProcessName -match "Peachw|Sage50|peachtree")
        })
    foreach ($p in $procs) {
        try {
            $el = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
            if ($el) { return $el }
        }
        catch { }
    }
    return $null
}

function Find-UiaByName($parent, [string]$name, $scope) {
    if ($null -eq $parent) { return $null }
    if (-not $scope) { $scope = [System.Windows.Automation.TreeScope]::Descendants }
    try {
        $c = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty, $name)
        return $parent.FindFirst($scope, $c)
    }
    catch { return $null }
}

function Invoke-UiaButton($win, [string]$name) {
    $btn = Find-UiaByName $win $name
    if (-not $btn) { return $false }
    try {
        $pat = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $pat.Invoke()
        return $true
    }
    catch { return $false }
}

function Set-UiaValue($el, [string]$text) {
    if ($null -eq $el) { return $false }
    try {
        $pat = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        $pat.SetValue($text)
        return $true
    }
    catch { return $false }
}

function Get-UiaEdits($win) {
    $c = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit)
    $found = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $c)
    $list = @()
    if ($found) {
        for ($i = 0; $i -lt $found.Count; $i++) { $list += $found.Item($i) }
    }
    return $list
}

function Find-SageInventoryWindow {
    $needles = @(
        "Inventory Items", "Maintain Inventory", "Inventario",
        "Articulos de inventario", "Artículos de inventario", "Articulos",
        "Mantener articulos", "Mantener artículos"
    )
    $windows = @()
    $root = $null
    try { $root = [System.Windows.Automation.AutomationElement]::RootElement } catch { }
    $main = Get-SageMainElement
    foreach ($start in @($main, $root)) {
        if ($null -eq $start) { continue }
        try {
            $c = New-Object System.Windows.Automation.PropertyCondition(
                [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                [System.Windows.Automation.ControlType]::Window)
            $found = $start.FindAll([System.Windows.Automation.TreeScope]::Descendants, $c)
            if ($found) {
                for ($i = 0; $i -lt $found.Count; $i++) { $windows += $found.Item($i) }
            }
        }
        catch { }
    }
    foreach ($w in $windows) {
        try {
            $n = [string]$w.Current.Name
            foreach ($need in $needles) {
                if ($n -and $n.IndexOf($need, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $w }
            }
        }
        catch { }
    }
    foreach ($name in @("Maintain Inventory Items", "Inventory Items", "Maintain Inventory")) {
        if ($main) {
            $el = Find-UiaByName $main $name
            if ($el) { return $el }
        }
        if ($root) {
            $el = Find-UiaByName $root $name ([System.Windows.Automation.TreeScope]::Descendants)
            if ($el) { return $el }
        }
    }
    return $null
}

function Invoke-UiaNamed($parent, [string]$name) {
    $el = Find-UiaByName $parent $name
    if (-not $el) { return $false }
    try {
        $pat = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $pat.Invoke()
        return $true
    }
    catch { }
    try {
        $pat = $el.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
        $pat.Expand()
        return $true
    }
    catch { }
    return $false
}

function Focus-SageWindow($el) {
    if ($null -eq $el) { return }
    try {
        $hwnd = [IntPtr]$el.Current.NativeWindowHandle
        $id = $null
        foreach ($p in @(Get-Process | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero })) {
            if ($p.MainWindowHandle -eq $hwnd) {
                $id = $p.Id
                break
            }
        }
        if (-not $id) {
            $sage = @(Get-Process | Where-Object {
                    $_.MainWindowHandle -ne [IntPtr]::Zero -and
                    ($_.ProcessName -match "Peachw|Sage50|peachtree")
                })
            if ($sage.Count -gt 0) { $id = $sage[0].Id }
        }
        if ($id) {
            $w = New-Object -ComObject WScript.Shell
            [void]$w.AppActivate($id)
        }
    }
    catch { }
}

function Open-SageInventoryWindow {
    $win = Find-SageInventoryWindow
    if ($win) { return $win }
    $main = Get-SageMainElement
    if (-not $main) {
        Write-Host "PROBE UI: no se encontro la ventana principal de Sage."
        return $null
    }
    Write-Host "Abriendo Maintain Inventory Items en Sage..."
    Focus-SageWindow $main
    Start-Sleep -Milliseconds 400
    foreach ($menu in @("Maintain", "Mantenimiento")) {
        if (Invoke-UiaNamed $main $menu) {
            Start-Sleep -Milliseconds 350
            foreach ($item in @("Inventory Items", "Inventory", "Inventario", "Articulos de inventario", "Artículos de inventario")) {
                if (Invoke-UiaNamed $main $item) {
                    Start-Sleep -Milliseconds 900
                    $win = Find-SageInventoryWindow
                    if ($win) { return $win }
                }
            }
        }
    }
    Focus-SageWindow $main
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait("%m")
    Start-Sleep -Milliseconds 400
    [System.Windows.Forms.SendKeys]::SendWait("i")
    Start-Sleep -Milliseconds 1000
    $win = Find-SageInventoryWindow
    if ($win) { return $win }
    [System.Windows.Forms.SendKeys]::SendWait("%m")
    Start-Sleep -Milliseconds 400
    [System.Windows.Forms.SendKeys]::SendWait("a")
    Start-Sleep -Milliseconds 1000
    return (Find-SageInventoryWindow)
}

function Reload-SageCreatedItem($factory, [string]$safeId, [string]$desc, [ref]$cache) {
    for ($try = 1; $try -le 6; $try++) {
        if ($try -gt 1) { Start-Sleep -Milliseconds 500 }
        $loaded = $null
        try { $loaded = $factory.Load($safeId) } catch { $loaded = $null }
        if ($loaded) {
            if ($cache) {
                if ($null -eq $cache.Value) { $cache.Value = @($loaded) }
                else { $cache.Value = @($cache.Value) + $loaded }
            }
            return $loaded
        }
        $list = $null
        try { $list = $factory.List() } catch { $list = Invoke-SageMethod $factory "List" }
        try { $list.Load() } catch { try { Invoke-SageMethod $list "Load" | Out-Null } catch {} }
        $items = @($list)
        if ($cache) { $cache.Value = $items }
        foreach ($it in $items) {
            $iid = [string](Get-SageProp $it "ID")
            if ($iid -and [string]::Equals($iid.Trim(), $safeId, [StringComparison]::OrdinalIgnoreCase)) {
                return $it
            }
        }
        if ($desc) {
            foreach ($it in $items) {
                $label = Get-SageItemLabel $it
                if ((Test-ItemNameMatch $desc $label)) { return $it }
            }
        }
    }
    return $null
}

function Restore-SageWindowUia {
    $main = Get-SageMainElement
    if (-not $main) { return $false }
    try {
        $pat = $main.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern)
        $state = $pat.Current.WindowVisualState
        if ("$state" -eq "Minimized") {
            $pat.SetWindowVisualState([System.Windows.Automation.WindowVisualState]::Maximized)
            Write-Host "UI: Sage restaurado por UIA WindowPattern."
            return $true
        }
        return $true
    }
    catch {
        return $false
    }
}

function New-SageInventoryItemUi([string]$id, [string]$desc, [string]$salesGl, [string]$linea = "") {
    Write-AhTrace -Fn "New-SageInventoryItemUi" -Paso "start" -Sku $id -Linea $linea -Detail $desc
    if (-not (Ensure-SageUiWin32)) {
        Write-AhTrace -Fn "New-SageInventoryItemUi" -Paso "Ensure-SageUiWin32" -Sku $id -Linea $linea -Detail "SageUiHost no cargo (Add-Type fallo)" -Ok $false
        return $false
    }
    try {
        Restore-SageWindowUia | Out-Null
        Write-AhTrace -Fn "New-SageInventoryItemUi" -Paso "OpenInventoryWindow" -Sku $id -Linea $linea -Detail "llamando Win32"
        $opened = [SageUiHost]::OpenInventoryWindow()
        Write-AhTrace -Fn "New-SageInventoryItemUi" -Paso "OpenInventoryWindow" -Sku $id -Linea $linea -Detail ("opened=" + $opened) -Ok $opened
        if (-not $opened) {
            Write-Host "UI: menu Win32 no abrio inventario; se intenta Maintain por UIA."
            Restore-SageWindowUia | Out-Null
            $uia = Open-SageInventoryWindow
            if ($uia) { Write-Host "UI: ventana inventario por menu UIA." }
            else {
                Write-AhTrace -Fn "New-SageInventoryItemUi" -Paso "Open-SageInventoryWindow" -Sku $id -Linea $linea -Detail "UIA tampoco abrio Maintain Inventory" -Ok $false
                Write-Host "[ITEM] FALLO ventana: Sage no abrio Maintain Inventory (minimizado o bloqueado)."
                $script:SageUiBlocked = $true
                return $false
            }
        }
        Write-AhTrace -Fn "New-SageInventoryItemUi" -Paso "CreateInventoryItem" -Sku $id -Linea $linea -Detail ("gl=" + $salesGl)
        $ok = [SageUiHost]::CreateInventoryItem($id, $desc, $salesGl)
        Write-AhTrace -Fn "New-SageInventoryItemUi" -Paso "CreateInventoryItem" -Sku $id -Linea $linea -Detail ("ok=" + $ok) -Ok $ok
        if ($ok) {
            Write-Host ("Item creado en Maintain Inventory: " + $id + " | " + $desc)
        }
        elseif (-not $opened) {
            $script:SageUiBlocked = $true
        }
        return [bool]$ok
    }
    catch {
        Write-AhTrace -Fn "New-SageInventoryItemUi" -Paso "exception" -Sku $id -Linea $linea -Detail $_.Exception.Message -Ok $false
        Write-Host ("AVISO UI Win32: " + $_.Exception.Message)
        return $false
    }
}

function Ensure-MissingSageItemsUi($session, $companyId, [ref]$openedRef, $records, [string]$salesGlId) {
    $opened = $openedRef.Value
    $missing = @()
    $invCache = $null
    $n = 0
    foreach ($rec in $records) {
        $n++
        $sku = Get-RecordItemCodigo $rec
        $desc = Get-RecordText $rec "descripcion"
        if (-not $desc) { $desc = "Linea $n" }
        if (-not $sku) { continue }
        $hit = Find-SageInventoryItem $opened $sku $desc ([ref]$invCache)
        if (-not $hit) {
            Write-AhTrace -Fn "Ensure-MissingSageItemsUi" -Paso "falta" -Sku $sku -Linea ([string]$n) -Detail $desc -Ok $false
            Write-Host ("[ITEM] falta en Sage: " + $sku + " | " + $desc)
            $missing += @{ sku = [string]$sku; desc = [string]$desc; linea = [string]$n }
        }
        else {
            Write-AhTrace -Fn "Ensure-MissingSageItemsUi" -Paso "ya_existe" -Sku $sku -Linea ([string]$n) -Detail "MATCH" -Ok $true
            Write-Host ("[ITEM] ya existe: " + $sku)
        }
    }
    if ($missing.Count -lt 1) { return $opened }
    Write-Host ("[ITEM] Cierro empresa SDK (" + $missing.Count + " items) para que Sage abra Maintain Inventory.")
    try { $opened.Close() } catch {}
    $openedRef.Value = $null
    Start-Sleep -Milliseconds 900
    $script:SageUiBlocked = $false
    foreach ($m in $missing) {
        if ($script:SageUiBlocked) {
            Write-AhTrace -Fn "Ensure-MissingSageItemsUi" -Paso "omitido" -Sku $m.sku -Linea $m.linea -Detail "SageUiBlocked" -Ok $false
            Write-Host ("[ITEM] UI omitido (Sage minimizado/bloqueado): " + $m.sku)
            continue
        }
        Write-AhTrace -Fn "Ensure-MissingSageItemsUi" -Paso "UI" -Sku $m.sku -Linea $m.linea -Detail $m.desc
        Write-Host ("[ITEM] UI (SDK cerrado): " + $m.sku + " | " + $m.desc)
        $ok = New-SageInventoryItemUi $m.sku $m.desc $salesGlId $m.linea
        if ($ok) { Write-Host ("[ITEM] UI creo: " + $m.sku) }
        else { Write-Host ("[ITEM] UI no creo: " + $m.sku) }
    }
    Write-Host "[ITEM] Reabro empresa via SDK."
    $opened = $session.Open($companyId)
    $openedRef.Value = $opened
    return $opened
}

function New-SageItemId([string]$sku, [string]$desc) {
    $raw = if ($sku) { $sku.Trim() } else { "" }
    if (-not $raw) {
        $raw = (Normalize-ItemName $desc) -replace " ", ""
        if ($raw.Length -gt 16) { $raw = $raw.Substring(0, 16) }
        $raw = "AH" + $raw
    }
    $raw = $raw -replace "[^A-Za-z0-9\-]", ""
    if (-not $raw) { $raw = "AH" + (Get-Date).ToString("HHmmss") }
    if ($raw.Length -gt 20) { $raw = $raw.Substring(0, 20) }
    return $raw
}

function Get-InventoryFactory($company) {
    $factories = Get-SageProp $company "Factories"
    if ($null -eq $factories) { return $null }
    foreach ($fname in @("InventoryItemFactory", "ItemFactory", "InventoryFactory")) {
        $factory = Get-SageProp $factories $fname
        if ($null -ne $factory) {
            Write-Host ("  Factory inventario: " + $fname)
            return $factory
        }
    }
    return $null
}

function Get-NextNumericSageItemId($items, [int]$offset = 1) {
    $max = 0
    foreach ($it in @($items)) {
        $id = [string](Get-SageProp $it "ID")
        if ($id -match '^[0-9]{1,6}$') {
            try {
                $n = [int]$id
                if ($n -gt $max) { $max = $n }
            }
            catch { }
        }
    }
    if ($max -lt 1) { $max = 1000 }
    return [string]($max + $offset)
}

function Get-CandidateItemIds([string]$sku, [string]$desc, $items) {
    $ids = @()
    $alpha = New-SageItemId $sku $desc
    if ($alpha) { $ids += $alpha }
    if (-not $sku) {
        $num = Get-NextNumericSageItemId $items 1
        if ($num -and ($ids -notcontains $num)) { $ids += $num }
    }
    return @($ids)
}

function Fill-NewSageItem($item, [string]$safeId, [string]$safeDesc, $salesAcctRef, $template, $skuRaw) {
    Set-SageProp $item "ID" $safeId | Out-Null
    Set-SageProp $item "ItemID" $safeId | Out-Null
    Set-SageProp $item "Description" $safeDesc | Out-Null
    Set-SageProp $item "SalesDescription" $safeDesc | Out-Null
    if ($template) { Copy-SageItemTemplate $item $template }
    if ($salesAcctRef) { Set-SageProp $item "SalesAccountReference" $salesAcctRef | Out-Null }
    foreach ($p in @("Class", "ItemClass", "ItemType", "Type")) {
        Set-SageProp $item $p 1 | Out-Null
    }
    if ($skuRaw -and $skuRaw -ne $safeId) {
        foreach ($p in @("UPC", "UPCCode", "SKU", "PartNumber", "VendorPartNumber")) {
            Set-SageProp $item $p $skuRaw | Out-Null
        }
    }
}

function Try-CopySageItem($factory, $template, [string]$newId, [string]$newDesc, $salesAcctRef) {
    if ($null -eq $template) {
        Write-Host "[ITEM] sin plantilla para Copy/Duplicate."
        return $null
    }
    foreach ($name in @("Copy", "Duplicate", "Clone")) {
        $copy = $null
        try { $copy = Invoke-SageMethod $template $name } catch { $copy = $null }
        if ($null -eq $copy) {
            try { $copy = Invoke-SageMethod $factory $name } catch { $copy = $null }
        }
        if ($null -eq $copy) { continue }
        Fill-NewSageItem $copy $newId $newDesc $salesAcctRef $template $newId
        try {
            Save-SageEntity $copy
            Write-Host ("[ITEM] CREADO SDK " + $name + ": " + $newId + " | " + $newDesc)
            return $copy
        }
        catch {
            $msg = $_.Exception.Message
            if ($_.Exception.InnerException) { $msg = $_.Exception.InnerException.Message }
            Write-Host ("[ITEM] FALLO SDK " + $name + ": " + $msg)
        }
    }
    return $null
}

function Get-TemplateInventoryItem($items) {
    foreach ($it in @($items)) {
        try {
            if ($it.SalesAccountReference) { return $it }
        }
        catch { }
        if (Get-SageProp $it "SalesAccountReference") { return $it }
    }
    foreach ($it in @($items)) {
        if ($it) { return $it }
    }
    return $null
}

function Copy-SageItemTemplate($dest, $template) {
    if ($null -eq $dest -or $null -eq $template) { return }
    foreach ($p in @(
            "Class", "ItemClass", "ItemType", "Type",
            "SalesAccountReference", "InventoryAccountReference",
            "CostOfSalesAccountReference", "COGSAccountReference",
            "Costing", "CostingMethod",
            "IsTaxable", "TaxType", "SalesTaxType",
            "StockingUnit", "StockingUM", "SalesUM", "UnitOfMeasure"
        )) {
        $v = Get-SageProp $template $p
        if ($null -ne $v) { Set-SageProp $dest $p $v | Out-Null }
    }
}

function New-SageInventoryItem($company, [string]$sku, [string]$desc, $salesAcctRef, [string]$salesGlId, [ref]$cache) {
    Write-AhTrace -Fn "New-SageInventoryItem" -Paso "start" -Sku $sku -Detail $desc
    $factory = Get-InventoryFactory $company
    if ($null -eq $factory) {
        Write-AhTrace -Fn "New-SageInventoryItem" -Paso "factory" -Sku $sku -Detail "InventoryItemFactory=null" -Ok $false
        return $null
    }

    $safeDesc = Clip-SageText $(if ($desc) { $desc } else { "ITEM" }) 30
    $salesId = $salesGlId
    if (-not $salesId) { $salesId = Get-SageGlAccountId $salesAcctRef }
    if (-not $salesId) { $salesId = Get-RefId $salesAcctRef }
    $items = $null
    if ($cache -and $null -ne $cache.Value) { $items = $cache.Value }
    else {
        $items = @(Get-InventoryList $factory $cache)
    }
    $template = Get-TemplateInventoryItem $items
    if (-not $salesId -and $template) {
        $salesId = Get-SageGlAccountId (Get-SageProp $template "SalesAccountReference")
    }

    $candidateIds = @(Get-CandidateItemIds $sku $desc $items)
    Write-Host ("[ITEM] IDs a probar: " + ($candidateIds -join ", "))

    foreach ($safeId in $candidateIds) {
        $existing = $null
        try { $existing = $factory.Load($safeId) } catch { }
        if ($existing) {
            Write-Host ("[ITEM] MATCH ID: " + $safeId + " | " + (Get-SageItemLabel $existing))
            return $existing
        }

        Write-Host ("[ITEM] Intentando Create() SDK: " + $safeId + " | " + $safeDesc)
        $item = Invoke-SageFactoryCreate $factory
        if ($null -ne $item) {
            Fill-NewSageItem $item $safeId $safeDesc $salesAcctRef $template $sku
            try {
                Save-SageEntity $item
                Write-Host ("[ITEM] CREADO SDK: " + $safeId + " | " + $safeDesc)
                if ($cache) {
                    if ($null -eq $cache.Value) { $cache.Value = @($item) }
                    else { $cache.Value = @($cache.Value) + $item }
                }
                return $item
            }
            catch {
                $msg = $_.Exception.Message
                if ($_.Exception.InnerException) { $msg = $_.Exception.InnerException.Message }
                Write-Host ("[ITEM] FALLO SDK: " + $msg)
            }
        }
        else {
            Write-AhTrace -Fn "New-SageInventoryItem" -Paso "Create" -Sku $safeId -Detail "SDK Create() no existe" -Ok $false
            Write-Host "[ITEM] SDK no puede Create() inventario. Sigue copia/COM."
        }

        $copied = Try-CopySageItem $factory $template $safeId $safeDesc $salesAcctRef
        if ($copied) { return $copied }
    }

    foreach ($safeId in $candidateIds) {
        Write-Host ("[ITEM] Intentando COM: " + $safeId + " | " + $safeDesc)
        if (Import-SageInventoryItemCom $safeId $safeDesc $salesId) {
            Start-Sleep -Milliseconds 800
            if ($cache) { $cache.Value = $null }
            $loaded = Reload-SageCreatedItem $factory $safeId $desc $cache
            if ($loaded) {
                Write-AhTrace -Fn "New-SageInventoryItem" -Paso "COM" -Sku $safeId -Detail "CREADO COM" -Ok $true
                Write-Host ("[ITEM] CREADO COM: " + $safeId + " | " + $safeDesc)
                return $loaded
            }
            Write-AhTrace -Fn "New-SageInventoryItem" -Paso "COM" -Sku $safeId -Detail "import OK pero Load no" -Ok $false
            Write-Host "[ITEM] FALLO COM: import OK pero no aparece en Sage SDK."
        }
        else {
            Write-AhTrace -Fn "New-SageInventoryItem" -Paso "COM" -Sku $safeId -Detail "no se pudo importar" -Ok $false
            Write-Host "[ITEM] FALLO COM: no se pudo importar."
        }
    }

    foreach ($safeId in $candidateIds) {
        if ($script:SageUiBlocked) {
            Write-Host ("[ITEM] UI omitido (Sage minimizado/bloqueado): " + $safeId)
            break
        }
        Write-Host ("[ITEM] Intentando ventana Maintain Inventory: " + $safeId + " | " + $safeDesc)
        if (New-SageInventoryItemUi $safeId $safeDesc $salesId) {
            Start-Sleep -Milliseconds 1000
            if ($cache) { $cache.Value = $null }
            $loaded = Reload-SageCreatedItem $factory $safeId $desc $cache
            if ($loaded) {
                Write-AhTrace -Fn "New-SageInventoryItem" -Paso "UI" -Sku $safeId -Detail "CREADO ventana" -Ok $true
                Write-Host ("[ITEM] CREADO ventana: " + $safeId + " | " + $safeDesc)
                return $loaded
            }
            Write-AhTrace -Fn "New-SageInventoryItem" -Paso "UI" -Sku $safeId -Detail "Save pero Load no" -Ok $false
            Write-Host "[ITEM] FALLO ventana: se pulso Save pero el item no aparece."
        }
        else {
            Write-AhTrace -Fn "New-SageInventoryItem" -Paso "UI" -Sku $safeId -Detail "no se abrio Maintain Inventory Items" -Ok $false
            Write-Host "[ITEM] FALLO ventana: no se abrio Maintain Inventory Items."
        }
    }

    Write-AhTrace -Fn "New-SageInventoryItem" -Paso "FAIL" -Sku $sku -Detail $safeDesc -Ok $false
    Write-Host ("[ITEM] FALLO crear: codigo=" + $sku + " | " + $safeDesc)
    return $null
}

function Get-InventoryList($factory, [ref]$cache) {
    if ($null -eq $factory) { return @() }
    $list = $null
    try { $list = $factory.List() } catch { $list = Invoke-SageMethod $factory "List" }
    if ($null -eq $list) { return @() }
    try { $list.Load() } catch { try { Invoke-SageMethod $list "Load" | Out-Null } catch {} }
    $items = @($list)
    if ($cache) { $cache.Value = $items }
    return $items
}

function Set-SageLineInventoryItem($line, $item) {
    if ($null -eq $line -or $null -eq $item) { return $false }
    $ok = $false
    $key = $null
    try { $key = $item.Key } catch { }
    if ($key) {
        foreach ($p in @("InventoryItemReference", "ItemReference")) {
            if (Set-SageProp $line $p $key) { $ok = $true }
        }
    }
    $id = [string](Get-SageProp $item "ID")
    if ($id) {
        foreach ($p in @("ItemID", "InventoryItemID", "Item")) {
            if (Set-SageProp $line $p $id) { $ok = $true }
        }
    }
    if (Set-SageProp $line "IsInventory" $true) { $ok = $true }
    return $ok
}

function Apply-SageTax($target, $tax, [string]$taxId) {
    if ($null -eq $target) { return $false }
    $ok = $false
    if ($tax) {
        $key = $null
        try { $key = $tax.Key } catch { }
        if ($key) {
            foreach ($p in @("SalesTaxCodeReference", "TaxCodeReference", "SalesTaxReference", "TaxReference")) {
                if (Set-SageProp $target $p $key) {
                    Write-Host ("  Impuesto Sage: " + $p)
                    $ok = $true
                }
            }
        }
        $id = [string](Get-SageProp $tax "ID")
        if (-not $id) { $id = $taxId }
        foreach ($p in @("SalesTaxCode", "TaxCode", "Tax", "SalesTaxID", "TaxID", "SalesTaxCodeID")) {
            if ($id -and (Set-SageProp $target $p $id)) {
                Write-Host ("  Impuesto Sage: " + $p + "=" + $id)
                $ok = $true
            }
        }
    }
    elseif ($taxId) {
        foreach ($p in @("SalesTaxCode", "TaxCode", "Tax", "SalesTaxID", "TaxID", "SalesTaxCodeID")) {
            if (Set-SageProp $target $p $taxId) {
                Write-Host ("  Impuesto Sage: " + $p + "=" + $taxId)
                $ok = $true
            }
        }
    }
    try {
        $asm = $target.GetType().Assembly
        foreach ($enumName in @("Sage.Peachtree.API.TaxType", "Sage.Peachtree.API.SalesTaxType")) {
            $enumType = $asm.GetType($enumName)
            if ($null -eq $enumType) { continue }
            $taxable = [Enum]::Parse($enumType, "Taxable")
            foreach ($p in @("TaxType", "SalesTaxType")) {
                if (Set-SageProp $target $p $taxable) { $ok = $true }
            }
        }
    }
    catch { }
    Set-SageProp $target "IsTaxable" $true | Out-Null
    return $ok
}

function Save-SageInvoice($invoice) {
    $m = $invoice.GetType().GetMethod("Save", [Type]::EmptyTypes)
    if ($null -eq $m) {
        throw "Save() no existe en " + $invoice.GetType().Name
    }
    try {
        $m.Invoke($invoice, $null) | Out-Null
    }
    catch {
        $inner = $_.Exception
        if ($inner.InnerException) { $inner = $inner.InnerException }
        throw $inner
    }
}

function Get-SageInvoiceNoProp($inv) {
    foreach ($p in @("ReferenceNumber", "InvoiceNumber", "Number", "ID")) {
        $v = Get-SageProp $inv $p
        if ($v) {
            $s = ([string]$v).Trim()
            if ($s) { return $s }
        }
    }
    return ""
}

function Test-AhInvoiceNo([string]$n) {
    if (-not $n) { return $false }
    return $n.StartsWith("AH", [StringComparison]::OrdinalIgnoreCase)
}

function Test-AhOnlySeq([string]$n, [string[]]$seqs) {
    if (-not (Test-AhInvoiceNo $n)) { return $false }
    if (-not $seqs -or $seqs.Count -lt 1) { return $true }
    foreach ($s in $seqs) {
        $t = ([string]$s).Trim()
        if (-not $t) { continue }
        if ($n.IndexOf("-R-" + $t, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
    }
    return $false
}

function Remove-SageInvoiceEntity($inv) {
    $last = $null
    foreach ($name in @("Delete", "Remove")) {
        try {
            $m = $inv.GetType().GetMethod($name, [Type]::EmptyTypes)
            if ($null -eq $m) { continue }
            $m.Invoke($inv, $null) | Out-Null
            return
        }
        catch {
            $last = $_.Exception
            if ($last.InnerException) { $last = $last.InnerException }
        }
    }
    try {
        foreach ($m in $inv.GetType().GetMethods()) {
            if ($m.Name -ne "Delete") { continue }
            $pars = $m.GetParameters()
            if ($pars.Count -eq 1 -and $pars[0].ParameterType -eq [bool]) {
                $m.Invoke($inv, @($true)) | Out-Null
                return
            }
        }
    }
    catch {
        $last = $_.Exception
        if ($last.InnerException) { $last = $last.InnerException }
    }
    if ($last) { throw $last }
    throw "Delete() no existe en " + $inv.GetType().Name
}

function Remove-SageAhInvoices($company, [string]$onlySeq) {
    $seqs = @()
    if ($onlySeq) {
        $seqs = @($onlySeq.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
    $factories = Get-SageProp $company "Factories"
    $factory = $null
    foreach ($name in @("SalesInvoiceFactory", "SalesJournalFactory", "InvoiceFactory")) {
        $factory = Get-SageProp $factories $name
        if ($null -ne $factory) { break }
    }
    if ($null -eq $factory) { throw "no hay SalesInvoiceFactory" }
    $list = $null
    try { $list = $factory.List() } catch { $list = Invoke-SageMethod $factory "List" }
    if ($null -eq $list) { throw "no se pudo List() facturas" }
    foreach ($expr in @(
            'ReferenceNumber.StartsWith("AH")',
            "ReferenceNumber LIKE 'AH%'",
            'InvoiceNumber.StartsWith("AH")'
        )) {
        try {
            $list.FilterExpression = $expr
            Write-Host ("FilterExpression: " + $expr)
            break
        }
        catch { }
    }
    try { $list.Load() } catch { try { Invoke-SageMethod $list "Load" | Out-Null } catch {} }
    $all = @($list)
    Write-Host ("Facturas cargadas de Sage: " + $all.Count)
    $targets = @()
    foreach ($inv in $all) {
        $n = Get-SageInvoiceNoProp $inv
        if (Test-AhOnlySeq $n $seqs) { $targets += ,$inv }
    }
    Write-Host ("Facturas AH a borrar: " + $targets.Count)
    if ($targets.Count -lt 1) {
        Write-Host "OK - facturas AH borradas: 0  fallos: 0"
        return
    }
    $ok = 0
    $fail = 0
    foreach ($inv in $targets) {
        $n = Get-SageInvoiceNoProp $inv
        try {
            Remove-SageInvoiceEntity $inv
            Write-Host ("Borrada: " + $n)
            $ok++
        }
        catch {
            $msg = $_.Exception.Message
            if ($_.Exception.InnerException) { $msg = $_.Exception.InnerException.Message }
            Write-Host ("NO se pudo borrar " + $n + ": " + $msg)
            $fail++
        }
    }
    Write-Host ("OK - facturas AH borradas: " + $ok + "  fallos: " + $fail)
}

function ConvertTo-AhJsonEsc([string]$s) {
    if ($null -eq $s) { return "" }
    return ((([string]$s).Replace('\', '\\')).Replace('"', '\"').Replace("`r", "").Replace("`n", " "))
}

function Write-InvoiceCard {
    param(
        [bool]$Ok,
        [string]$Ref,
        [string]$Date,
        [string]$CustomerId,
        [string]$CustomerName,
        [string]$Total,
        $Lines,
        [string]$Detail = ""
    )
    $parts = @()
    foreach ($ln in @($Lines)) {
        $okBit = if ($ln.ok) { "true" } else { "false" }
        $parts += (
            '{"n":' + [int]$ln.n +
            ',"sku":"' + (ConvertTo-AhJsonEsc ([string]$ln.sku)) +
            '","qty":"' + (ConvertTo-AhJsonEsc ([string]$ln.qty)) +
            '","ok":' + $okBit +
            ',"err":"' + (ConvertTo-AhJsonEsc ([string]$ln.err)) + '"}'
        )
    }
    $okBit = if ($Ok) { "true" } else { "false" }
    $json = (
        '{"ok":' + $okBit +
        ',"ref":"' + (ConvertTo-AhJsonEsc $Ref) +
        '","date":"' + (ConvertTo-AhJsonEsc $Date) +
        '","customer_id":"' + (ConvertTo-AhJsonEsc $CustomerId) +
        '","customer_name":"' + (ConvertTo-AhJsonEsc $CustomerName) +
        '","total":"' + (ConvertTo-AhJsonEsc $Total) +
        '","detail":"' + (ConvertTo-AhJsonEsc $Detail) +
        '","lines":[' + ($parts -join ',') + ']}'
    )
    Write-Host ("[CARD] " + $json)
}

function Write-ProbeResult([string]$via, [string]$id, [bool]$ok, [string]$detail) {
    $flag = if ($ok) { "OK" } else { "NO" }
    Write-Host ("PROBE " + $via + "=" + $flag + " id=" + $id + $(if ($detail) { " " + $detail } else { "" }))
}

function Invoke-SageItemProbe($company) {
    Write-Host "PROBE items: match-only (no se crean items)"
    $want = @("S-020", "P-001", "N-001")
    $cache = $null
    $miss = @()
    foreach ($sku in $want) {
        $hit = Find-SageInventoryItem $company $sku "" ([ref]$cache)
        if ($hit) {
            Write-ProbeResult "MATCH" $sku $true (Get-SageItemLabel $hit)
        }
        else {
            Write-ProbeResult "MATCH" $sku $false "no existe en Sage"
            $miss += $sku
        }
    }
    if ($miss.Count -gt 0) {
        Fail 16 ("PROBE: no existen en Sage: " + ($miss -join ", "))
    }
    Write-Host ("PROBE RESUMEN MATCH=OK SKUS=" + ($want -join ","))
    Write-Host "PROBE items: listo. Match de S-020, P-001, N-001."
    return
    Write-Host "PROBE items: inicio"
    $factory = Get-InventoryFactory $company
    if ($null -eq $factory) {
        Fail 16 "PROBE: no hay InventoryItemFactory"
    }
    Dump-SageMethods $factory "InventoryItemFactory"
    $cache = $null
    $items = @(Get-InventoryList $factory ([ref]$cache))
    Write-Host ("PROBE catalogo items: " + $items.Count)
    $numericCount = 0
    $alphaCount = 0
    foreach ($it in $items) {
        $iid = [string](Get-SageProp $it "ID")
        if ($iid -match '^[0-9]+$') { $numericCount++ } elseif ($iid) { $alphaCount++ }
    }
    Write-Host ("PROBE ids numericos=" + $numericCount + " alfanumericos=" + $alphaCount)
    $template = Get-TemplateInventoryItem $items
    $salesRef = Find-SageGlAccount $company "4001"
    $salesId = "4001"
    $desc = Clip-SageText "AHTEST PLAYA BLANCA" 30
    $stamp = Get-Date -Format "HHmmss"
    $sdkOk = $false
    $copyOk = $false
    $comOk = $false
    $uiOk = $false
    $alphaOk = $false
    $numOk = $false

    $alphaSdk = "AHTEST" + $stamp
    if ($alphaSdk.Length -gt 20) { $alphaSdk = $alphaSdk.Substring(0, 20) }
    Write-Host ("PROBE SDK Create() id=" + $alphaSdk)
    $created = Invoke-SageFactoryCreate $factory
    if ($created) {
        Fill-NewSageItem $created $alphaSdk $desc $salesRef $template $alphaSdk
        try {
            Save-SageEntity $created
            Start-Sleep -Milliseconds 400
            $cache = $null
            $loaded = Reload-SageCreatedItem $factory $alphaSdk $desc ([ref]$cache)
            $sdkOk = [bool]$loaded
            if ($sdkOk) { $alphaOk = $true }
            Write-ProbeResult "SDK" $alphaSdk $sdkOk $(if ($loaded) { Get-SageItemLabel $loaded } else { "Save OK pero Load no" })
        }
        catch {
            $msg = $_.Exception.Message
            if ($_.Exception.InnerException) { $msg = $_.Exception.InnerException.Message }
            Write-ProbeResult "SDK" $alphaSdk $false $msg
        }
    }
    else {
        Write-ProbeResult "SDK" $alphaSdk $false "Create() no existe"
        try {
            foreach ($m in $factory.GetType().GetMethods()) {
                if ($m.Name -notlike "*Create*") { continue }
                $pars = $m.GetParameters()
                if ($pars.Count -ne 1 -or -not $pars[0].ParameterType.IsEnum) { continue }
                $ei = 0
                foreach ($v in [enum]::GetValues($pars[0].ParameterType)) {
                    $ei++
                    $enumId = "AHTE" + $stamp + $ei
                    if ($enumId.Length -gt 20) { $enumId = $enumId.Substring(0, 20) }
                    try {
                        $obj = $m.Invoke($factory, @($v))
                        if ($null -eq $obj) {
                            Write-ProbeResult ("SDK " + $v) $enumId $false "Create devolvio null"
                            continue
                        }
                        Fill-NewSageItem $obj $enumId $desc $salesRef $template $enumId
                        Save-SageEntity $obj
                        $cache = $null
                        $loaded = Reload-SageCreatedItem $factory $enumId $desc ([ref]$cache)
                        $ok = [bool]$loaded
                        if ($ok) { $sdkOk = $true; $alphaOk = $true }
                        Write-ProbeResult ("SDK " + $v) $enumId $ok ""
                        if ($ok) { break }
                    }
                    catch {
                        $msg = $_.Exception.Message
                        if ($_.Exception.InnerException) { $msg = $_.Exception.InnerException.Message }
                        Write-ProbeResult ("SDK " + $v) $enumId $false $msg
                    }
                }
            }
        }
        catch { }
    }

    $copyId = "AHTESTC" + $stamp
    if ($copyId.Length -gt 20) { $copyId = $copyId.Substring(0, 20) }
    Write-Host ("PROBE SDK Copy id=" + $copyId)
    $copied = Try-CopySageItem $factory $template $copyId $desc $salesRef
    if ($copied) {
        $cache = $null
        $loaded = Reload-SageCreatedItem $factory $copyId $desc ([ref]$cache)
        $copyOk = [bool]$loaded
        if ($copyOk) { $alphaOk = $true }
        Write-ProbeResult "COPY" $copyId $copyOk ""
    }
    else {
        Write-ProbeResult "COPY" $copyId $false "sin Copy/Duplicate"
    }

    $comAlpha = "AHTESTX" + $stamp
    if ($comAlpha.Length -gt 20) { $comAlpha = $comAlpha.Substring(0, 20) }
    Write-Host ("PROBE COM XML/CSV alpha id=" + $comAlpha)
    if (Import-SageInventoryItemCom $comAlpha $desc $salesId) {
        Start-Sleep -Milliseconds 800
        $cache = $null
        $loaded = Reload-SageCreatedItem $factory $comAlpha $desc ([ref]$cache)
        $comOk = [bool]$loaded
        if ($comOk) { $alphaOk = $true }
        Write-ProbeResult "COM" $comAlpha $comOk $(if ($loaded) { "" } else { "import OK Load no" })
    }
    else {
        Write-ProbeResult "COM" $comAlpha $false "import rechazo"
    }

    $numId = Get-NextNumericSageItemId $items 1
    Write-Host ("PROBE COM numeric id=" + $numId)
    if (Import-SageInventoryItemCom $numId $desc $salesId) {
        Start-Sleep -Milliseconds 800
        $cache = $null
        $loaded = Reload-SageCreatedItem $factory $numId $desc ([ref]$cache)
        $ok = [bool]$loaded
        if ($ok) { $comOk = $true; $numOk = $true }
        Write-ProbeResult "COMNUM" $numId $ok $(if ($loaded) { "" } else { "import OK Load no" })
    }
    else {
        Write-ProbeResult "COMNUM" $numId $false "import rechazo"
    }

    $uiNum = Get-NextNumericSageItemId $items 2
    Write-Host "PROBE UI: cierro empresa SDK para Maintain Inventory"
    try { $company.Close() } catch {}
    Start-Sleep -Milliseconds 800

    $uiId = "AHTESTU" + $stamp
    if ($uiId.Length -gt 20) { $uiId = $uiId.Substring(0, 20) }
    Write-Host ("PROBE UI Maintain Inventory id=" + $uiId)
    $uiMade = New-SageInventoryItemUi $uiId $desc $salesId
    Write-Host ("PROBE UI numeric id=" + $uiNum)
    $uiNumMade = New-SageInventoryItemUi $uiNum $desc $salesId

    Write-Host "PROBE UI: reabro empresa SDK"
    if ($script:SageSession -and $script:SageCompanyId) {
        $company = $script:SageSession.Open($script:SageCompanyId)
        $factory = Get-InventoryFactory $company
    }
    if ($uiMade) {
        Start-Sleep -Milliseconds 400
        $cache = $null
        $loaded = Reload-SageCreatedItem $factory $uiId $desc ([ref]$cache)
        $uiOk = [bool]$loaded
        if ($uiOk) { $alphaOk = $true }
        Write-ProbeResult "UI" $uiId $uiOk $(if ($loaded) { "" } else { "Save UI pero Load no" })
    }
    else {
        Write-ProbeResult "UI" $uiId $false "no se abrio ventana"
    }
    if ($uiNumMade) {
        Start-Sleep -Milliseconds 400
        $cache = $null
        $loaded = Reload-SageCreatedItem $factory $uiNum $desc ([ref]$cache)
        $ok = [bool]$loaded
        if ($ok) { $uiOk = $true; $numOk = $true }
        Write-ProbeResult "UINUM" $uiNum $ok $(if ($loaded) { "" } else { "Save UI pero Load no" })
    }
    else {
        Write-ProbeResult "UINUM" $uiNum $false "no se abrio ventana"
    }

    Write-Host ("PROBE RESUMEN SDK=" + $(if ($sdkOk) { "OK" } else { "NO" }) + " COPY=" + $(if ($copyOk) { "OK" } else { "NO" }) + " COM=" + $(if ($comOk) { "OK" } else { "NO" }) + " UI=" + $(if ($uiOk) { "OK" } else { "NO" }) + " ALPHA=" + $(if ($alphaOk) { "OK" } else { "NO" }) + " NUMERIC=" + $(if ($numOk) { "OK" } else { "NO" }))
    if (-not $sdkOk -and -not $copyOk -and -not $comOk -and -not $uiOk) {
        Fail 16 "PROBE: ninguna via creo un item. SDK no tiene Create. COM/ventana no dejaron un Item ID nuevo."
    }
    Write-Host "PROBE items: listo. Revisa Maintain Inventory Items (AHTEST* y el numero nuevo)."
}

if ([IntPtr]::Size -ne 4) {
    Fail 12 "Este script debe correr en PowerShell 32-bit (SysWOW64)."
}

$apiDir = "C:\Program Files (x86)\Sage\Peachtree\API"
if (-not (Test-Path "$apiDir\Sage.Peachtree.API.dll")) {
    Fail 10 "No se encontro Sage.Peachtree.API.dll"
}
if (-not (Test-Path $AppIdFile)) {
    Fail 13 "Falta app_id.txt"
}

$appId = (Get-Content -LiteralPath $AppIdFile -TotalCount 1).Trim()
if (-not $appId) {
    Fail 13 "app_id.txt esta vacio"
}

function Get-SageRefPrefix([string]$sucursal, $first = $null) {
    return Get-SageStoreLetter $sucursal $first
}

function Normalize-CompanyName([string]$value) {
    return [regex]::Replace($value.Trim(), "\s+", " ")
}

Write-Host "Auto-Hub - envio a Sage 50"
Write-Host "Empresa objetivo: $Company"
Write-Host "Application ID: (configurado, $($appId.Length) chars)"
Write-Host "Modo: $(if ($DeleteAh) { 'borrar facturas AH' } elseif ($AuthOnly) { 'autorizar Always Allow' } elseif ($ProbeItems) { 'probar crear items' } else { 'escritura' })"
Write-Host ""

[Reflection.Assembly]::LoadFrom("$apiDir\Sage.Peachtree.API.Resolver.dll") | Out-Null
[Reflection.Assembly]::LoadFrom("$apiDir\Sage.Peachtree.API.dll") | Out-Null
[Sage.Peachtree.API.Resolver.AssemblyInitializer]::Initialize()

$session = $null
$opened = $null
$code = 0
try {
    $session = New-Object Sage.Peachtree.API.PeachtreeSession
    $session.Begin($appId)
    $script:SageSession = $session
    Write-Host "Sesion iniciada: $($session.SessionActive)"

    $wanted = Normalize-CompanyName $Company
    $companyId = $null
    Write-Host "Companias registradas en Sage:"
    foreach ($id in $session.CompanyList()) {
        Write-Host ("  - " + $id.CompanyName)
        if ((Normalize-CompanyName $id.CompanyName) -eq $wanted) {
            $companyId = $id
            $script:SageCompanyId = $id
        }
    }
    Write-Host ""
    if ($null -eq $companyId) {
        Fail 1 "No se encontro la empresa: $Company"
    }

    Write-Host "Solicitando acceso..."
    $auth = $session.RequestAccess($companyId)
    Write-Host "Autorizacion: $auth"

    if ("$auth" -eq "Granted") {
        Write-Host "Already granted (Always Allow previo). No hace falta reabrir Sage."
    }
    elseif ("$auth" -eq "Pending") {
        Write-Host ""
        Write-Host "=== ACCION EN SAGE (una sola vez) ==="
        Write-Host "1. Deja Sage 50 ABIERTO (no lo cierres)."
        Write-Host "2. Abre la empresa: $Company"
        Write-Host "3. En el dialogo, elige ALWAYS ALLOW (no solo Allow)."
        Write-Host "Esperando hasta 3 minutos..."
        Write-Host ""
        for ($i = 1; $i -le 36; $i++) {
            Start-Sleep -Seconds 5
            $auth = $session.RequestAccess($companyId)
            Write-Host "  Reintento $i/36 -> $auth"
            if ("$auth" -eq "Granted" -or "$auth" -eq "Denied") { break }
        }
    }

    if ("$auth" -ne "Granted") {
        Fail 2 "sin autorizacion Granted. Estado: $auth. Deja Sage ABIERTO y elige Always Allow."
    }

    Write-Host "OK - Acceso Granted."
    if ($AuthOnly) {
        Write-Host "Ya no deberia pedir Allow en cada carga."
        $code = 0
    }
    elseif ($DeleteAh) {
        $opened = $session.Open($companyId)
        Write-Host "Empresa abierta via SDK."
        Write-Host "Borrando facturas AH de Sage..."
        Remove-SageAhInvoices $opened $OnlySeq
        $code = 0
    }
    elseif ($ProbeItems) {
        $opened = $session.Open($companyId)
        Write-Host "Empresa abierta via SDK."
        Invoke-SageItemProbe $opened
        $code = 0
    }
    else {
        $records = @(Get-InvoiceRecords $SampleJson)
        if ($records.Count -lt 1) {
            Fail 15 "sample sin lineas de factura: $SampleJson"
        }
        $lineChk = 0
        foreach ($rec in $records) {
            $lineChk++
            $skuChk = Get-RecordItemCodigo $rec
            if (-not $skuChk) {
                $descChk = Get-RecordText $rec "descripcion"
                if (-not $descChk) { $descChk = "Linea $lineChk" }
                Fail 16 ("linea " + $lineChk + " sin item_codigo de PsKloud | " + $descChk)
            }
        }

        $first = $records[0]
        $numeroOrigen = Get-RecordText $first "numero_factura"
        if (-not $numeroOrigen) { $numeroOrigen = "SIN-NUM" }
        $fechaRaw = Get-RecordText $first "fecha_emision"
        $fechaTxt = ""
        if ($fechaRaw.Length -ge 10) { $fechaTxt = $fechaRaw.Substring(0, 10) }
        elseif ($fechaRaw) { $fechaTxt = $fechaRaw }
        $fechaEmision = [datetime]::Today
        if ($fechaTxt) {
            try {
                $fechaEmision = [datetime]::ParseExact($fechaTxt, "yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture)
            }
            catch {
                try { $fechaEmision = [datetime]$fechaTxt } catch { }
            }
        }
        $psId = Get-RecordText $first "cliente_codigo"
        $psName = Get-RecordText $first "cliente_nombre"
        $sucursales = @()
        foreach ($rec in $records) {
            $s = Get-RecordText $rec "sucursal"
            if ($s -and $sucursales -notcontains $s) { $sucursales += $s }
        }
        $sucTxt = if ($sucursales.Count -gt 0) { ($sucursales -join ", ") } else { "SIN SUCURSAL" }
        $prefix = Get-SageRefPrefix $sucTxt $first
        $refNumber = Get-SageInvoiceNo $first $prefix $fechaEmision
        Write-Host ("Factura origen: " + $numeroOrigen + " (lineas=" + $records.Count + ")")
        Write-Host ("Fecha en Sage: " + $fechaEmision.ToString("yyyy-MM-dd") + " (fecha de la factura)")
        Write-Host ("Sucursal: " + $sucTxt)
        Write-Host ("Cliente PsKloud: " + $psId + " | " + $psName)
        Write-Host ("ReferenceNumber Sage: " + $refNumber)
        Write-Host ""

        $opened = $session.Open($companyId)
        Write-Host "Empresa abierta via SDK."

        $loadedCustomers = $null
        $customer = Find-SageCustomer $opened @($CustomerId, $psId) @($CustomerName, $psName) ([ref]$loadedCustomers)
        $createdNewCustomer = $false
        if ($null -eq $customer) {
            $wantId = if ($CustomerId) { $CustomerId } else { $psId }
            $wantName = if ($CustomerName) { $CustomerName } else { $psName }
            if (-not $wantId -and -not $wantName) {
                Write-Host "No hay match. Clientes en Sage (muestra):"
                Show-SageCustomers $loadedCustomers 25
                Fail 3 "factura sin cliente (ID y nombre vacios). No se crea ficha en Sage."
            }
            Write-Host ("Cliente no existe en Sage. Se crea: ID=" + $wantId + " Nombre=" + $wantName)
            $template = Get-TemplateCustomer $loadedCustomers
            if ($template) {
                Write-Host ("  GL copiado de: " + $template.ID + " | " + $template.Name)
            }
            $ruc = Get-RecordText $first "ruc"
            if ($ruc -eq "CF") { $ruc = "" }
            $direccion = Get-RecordText $first "cliente_direccion"
            if (-not $direccion) { $direccion = Get-RecordText $first "direccion" }
            try {
                $created = New-SageCustomer $opened $wantId $wantName $ruc $template $direccion
                $createdNewCustomer = $true
            }
            catch {
                Write-Host ("ERROR creando cliente: " + $_.Exception.Message)
                Fail 3 ("no se pudo crear el cliente en Sage. Buscado: ID=" + $wantId + " Nombre=" + $wantName)
            }
            $reloaded = $null
            $found = Find-SageCustomer $opened @($created.ID, $wantId) @($wantName) ([ref]$reloaded)
            $customer = if ($found) { $found } else { $created }
        }
        Write-Host ("Cliente Sage: " + $customer.ID + " | " + $customer.Name)
        if ($createdNewCustomer) {
            Write-Host "  Alta nueva por Auto-Hub (primera factura lleva marca CLIENTE NUEVO)."
        }

        $storeGl = Get-SageStoreGlIds $prefix
        $salesAcctRef = $null
        $discAcctRef = $null
        $salesGlId = [string]$storeGl.Sales
        $discGlId = [string]$storeGl.Discount
        if ($salesGlId) {
            $salesAcct = Find-SageGlAccount $opened $salesGlId
            if ($null -eq $salesAcct) {
                Fail 4 ("No esta la cuenta de ventas " + $salesGlId + " (" + $storeGl.Name + ") en Sage.")
            }
            $salesAcctRef = Get-SageAccountRef $salesAcct
            Write-Host ("GL ventas sucursal: " + $salesGlId + " " + $storeGl.Name)
        }
        if ($discGlId) {
            $discAcct = Find-SageGlAccount $opened $discGlId
            if ($null -eq $discAcct) {
                Fail 4 ("No esta la cuenta de descuento " + $discGlId + " (" + $storeGl.Name + ") en Sage.")
            }
            $discAcctRef = Get-SageAccountRef $discAcct
            Write-Host ("GL descuento sucursal: " + $discGlId + " " + $storeGl.Name)
        }
        if ($null -eq $salesAcctRef) {
            try { $salesAcctRef = $customer.UsualSalesAccountReference } catch {
                Write-Host ("AVISO UsualSalesAccountReference: " + $_.Exception.Message)
            }
            Write-Host "AVISO: sucursal sin mapa 4001/4002/4003. Se usa GL del cliente."
        }
        if ($null -eq $salesAcctRef) {
            Fail 4 ($customer.ID + " no tiene UsualSalesAccountReference (GL ventas).")
        }
        if ($null -eq $discAcctRef) { $discAcctRef = $salesAcctRef }

        $tasaHeader = Get-RecordDecimal $first "tasa_itbms" 0.07
        $taxId = "ITBMS"
        $tax = $null
        if ($tasaHeader -gt 0) {
            $tax = Find-SageSalesTax $opened $taxId
            if ($null -eq $tax) {
                Fail 7 "No esta el codigo de impuesto ITBMS en Sage (el primero del lookup, no ITBMS7)."
            }
        }

        Write-Host "Match de items existentes en Sage (no se crean)..."
        $invCache = $null
        $matched = @()
        $cardLines = @()
        $lineScan = 0
        $firstMiss = $null
        foreach ($rec in $records) {
            $lineScan++
            $sku = Get-RecordItemCodigo $rec
            $desc = Get-RecordText $rec "descripcion"
            if (-not $desc) { $desc = "Linea $lineScan" }
            $qty = Get-RecordDecimal $rec "cantidad" 1
            $sageItem = $null
            if ($sku) {
                $sageItem = Find-SageInventoryItem $opened $sku $desc ([ref]$invCache)
            }
            $okHit = $null -ne $sageItem
            $errTxt = ""
            if (-not $okHit) {
                $errTxt = if (-not $sku) { "sin item_codigo" } else { "no existe en Sage" }
                if ($null -eq $firstMiss) {
                    $firstMiss = @{ n = $lineScan; sku = $sku; desc = $desc; err = $errTxt }
                }
            }
            $cardLines += ,@{ n = $lineScan; sku = $sku; qty = [string]$qty; ok = $okHit; err = $errTxt }
            $matched += ,@{ rec = $rec; sku = $sku; desc = $desc; item = $sageItem }
        }
        $cardTotal = [string](Get-RecordDecimal $first "total_factura" 0)
        $cardDate = $fechaEmision.ToString("yyyy-MM-dd")
        if ($firstMiss) {
            $missingSkus = @(
                $cardLines |
                    Where-Object { -not $_.ok } |
                    ForEach-Object { [string]$_.sku } |
                    Where-Object { $_ } |
                    Select-Object -Unique
            )
            $missingCount = @($missingSkus).Count
            $missingWord = if ($missingCount -eq 1) { "item" } else { "items" }
            $missingList = @($missingSkus) -join ", "
            $msg = "faltan " + $missingCount + " " + $missingWord + " en Sage: " + $missingList
            Write-InvoiceCard $false $refNumber $cardDate $customer.ID $customer.Name $cardTotal $cardLines $msg
            Fail 16 $msg
        }

        Write-Host "Creando SalesInvoice via factory..."
        $invoice = New-SageInvoice $opened
        if ($null -eq $invoice) {
            Fail 5 "no se pudo Create() SalesInvoice."
        }
        Write-Host ("  Invoice tipo: " + $invoice.GetType().FullName)

        $assigned = $false
        $key = $null
        try { $key = $customer.Key } catch { }
        if ($null -ne $key) {
            Write-Host ("  Customer.Key tipo: " + $key.GetType().FullName)
            $assigned = Set-SageProp $invoice "CustomerReference" $key
        }
        if (-not $assigned) {
            $assigned = Set-SageProp $invoice "CustomerID" $customer.ID
        }
        if (-not $assigned) {
            Fail 8 "no se pudo asignar el cliente a la factura."
        }
        Write-Host "  Cliente asignado."
        if ($tax) {
            if (-not (Apply-SageTax $invoice $tax $taxId)) {
                Write-Host "  AVISO: no se pudo poner ITBMS en la cabecera; se intenta en cada linea."
            }
        }

        Set-SageProp $invoice "Date" $fechaEmision | Out-Null
        Set-SageProp $invoice "TransactionDate" $fechaEmision | Out-Null
        Set-SageProp $invoice "DatePosted" $fechaEmision | Out-Null
        Set-SageProp $invoice "ShipDate" $fechaEmision | Out-Null
        Set-SageProp $invoice "ReferenceNumber" $refNumber | Out-Null
        Set-SageProp $invoice "InvoiceNumber" $refNumber | Out-Null
        Set-SageProp $invoice "Number" $refNumber | Out-Null
        $po = $numeroOrigen
        if ($po.Length -gt 20) { $po = $po.Substring(0, 20) }
        if ($po -and $po -ne $refNumber) {
            Set-SageProp $invoice "CustomerPurchaseOrderNumber" $po | Out-Null
            Set-SageProp $invoice "CustomerPO" $po | Out-Null
        }
        $note = "AH " + $sucTxt + " | PsKloud " + $numeroOrigen + " id=" + (Get-RecordText $first "factura_id")
        if ($createdNewCustomer) {
            $note = "CLIENTE NUEVO | " + $note
        }
        Set-SageProp $invoice "Note" $note | Out-Null
        Set-SageProp $invoice "InternalNote" $note | Out-Null
        Set-SageProp $invoice "Memo" $note | Out-Null
        Write-Host ("  Date/TransactionDate = " + $fechaEmision.ToString("yyyy-MM-dd"))
        Write-Host ("  Nota Sage: " + $note)

        $lineNo = 0
        $netSum = [decimal]0
        foreach ($hit in $matched) {
            $lineNo++
            $rec = $hit.rec
            $sku = $hit.sku
            $desc = $hit.desc
            $sageItem = $hit.item
            $line = Add-SageInvoiceLine $invoice $opened
            if ($null -eq $line) {
                Fail 6 ("no se pudo crear linea " + $lineNo)
            }
            if (-not $sku) {
                Write-AhTrace -Fn "SalesInvoice" -Paso "item_codigo" -Linea ([string]$lineNo) -Detail $desc -Ok $false
                Fail 16 ("linea " + $lineNo + " sin item_codigo de PsKloud | " + $desc)
            }
            Write-AhTrace -Fn "SalesInvoice" -Paso "linea" -Sku $sku -Linea ([string]$lineNo) -Detail $desc
            if (-not $sageItem) {
                Fail 16 ("no existe en Sage codigo=" + $sku + " | " + $desc)
            }
            $suc = Get-RecordText $rec "sucursal"
            if ($suc) { $desc = "[" + $suc + "] " + $desc }
            if ($createdNewCustomer -and $lineNo -eq 1) {
                $desc = "[CLIENTE NUEVO] " + $desc
            }
            $qty = Get-RecordDecimal $rec "cantidad" 1
            $price = Round-Money (Get-RecordDecimal $rec "precio_unitario" 0)
            $amount = Round-Money ($qty * $price)
            $netSum += $amount
            Set-SageProp $line "Description" $desc | Out-Null
            Set-SageProp $line "Quantity" $qty | Out-Null
            Set-SageProp $line "QuantitySold" $qty | Out-Null
            Set-SageProp $line "UnitPrice" $price | Out-Null
            Set-SageProp $line "Amount" $amount | Out-Null
            if (-not (Set-SageLineInventoryItem $line $sageItem)) {
                $iid = [string](Get-SageProp $sageItem "ID")
                $okId = $false
                foreach ($p in @("ItemID", "InventoryItemID", "Item")) {
                    if ($iid -and (Set-SageProp $line $p $iid)) { $okId = $true }
                }
                if (-not $okId) {
                    Fail 16 ("no se pudo poner Item ID en linea " + $lineNo + " codigo=" + $iid)
                }
                Write-Host ("[ITEM] asignado por ItemID texto linea " + $lineNo + ": " + $iid)
            }
            if (-not (Set-SageLineGl $line $salesAcctRef)) {
                Write-Host ("  AVISO linea " + $lineNo + ": no se pudo poner GL ventas " + $salesGlId)
            }
            $lineTasa = Get-RecordDecimal $rec "tasa_itbms" $tasaHeader
            if ($tax -and $lineTasa -gt 0) {
                if (-not (Apply-SageTax $line $tax $taxId)) {
                    Write-Host ("  AVISO linea " + $lineNo + ": no se pudo asignar impuesto ITBMS")
                    Dump-SageType $line ("Linea " + $lineNo)
                }
            }
            $short = $desc
            if ($short.Length -gt 60) { $short = $short.Substring(0, 57) + "..." }
            $sageId = [string](Get-SageProp $sageItem "ID")
            $tag = if ($sageId) { $sageId } else { $sku }
            $itemNote = "item=" + $tag
            $glNote = if ($salesGlId) { $salesGlId } else { "cliente" }
            Write-Host ("  Linea " + $lineNo + ": qty=" + $qty + " price=" + $price + " amount=" + $amount + " tax=" + $(if ($tax -and $lineTasa -gt 0) { $taxId } else { "no" }) + " gl=" + $glNote + " " + $itemNote + " | " + $short)
        }

        $disc = Get-InvoiceDiscount $records
        if ($disc.Amount -gt 0) {
            $lineNo++
            $line = Add-SageInvoiceLine $invoice $opened
            if ($null -eq $line) {
                Fail 6 ("no se pudo crear linea de descuento " + $lineNo)
            }
            $desc = Format-DescuentoDesc $disc.Pct
            $qty = [decimal]1
            $price = -[decimal]$disc.Amount
            $amount = $price
            $netSum += $amount
            Set-SageProp $line "Description" $desc | Out-Null
            Set-SageProp $line "Quantity" $qty | Out-Null
            Set-SageProp $line "QuantitySold" $qty | Out-Null
            Set-SageProp $line "UnitPrice" $price | Out-Null
            Set-SageProp $line "Amount" $amount | Out-Null
            Set-SageProp $line "IsInventory" $false | Out-Null
            if (-not (Set-SageLineGl $line $discAcctRef)) {
                Write-Host ("  AVISO linea descuento: no se pudo poner GL " + $discGlId)
            }
            $lineTasa = Get-RecordDecimal $first "tasa_itbms" $tasaHeader
            if ($tax -and $lineTasa -gt 0) {
                if (-not (Apply-SageTax $line $tax $taxId)) {
                    Write-Host ("  AVISO linea " + $lineNo + ": no se pudo asignar impuesto ITBMS al descuento")
                }
            }
            $glNote = if ($discGlId) { $discGlId } else { "cliente" }
            Write-Host ("  Linea " + $lineNo + ": qty=" + $qty + " price=" + $price + " amount=" + $amount + " tax=" + $(if ($tax -and $lineTasa -gt 0) { $taxId } else { "no" }) + " gl=" + $glNote + " | " + $desc)
        }

        $docTotal = [decimal](Get-RecordDecimal $first "total_factura" 0)
        if ($docTotal -gt 0) {
            $docItbms = [decimal](Get-RecordDecimal $first "itbms_factura" 0)
            $estDoc = Round-Money ($netSum + $docItbms)
            $estCalc = if ($tasaHeader -gt 0) {
                Round-Money ($netSum + (Round-Money ($netSum * [decimal]$tasaHeader)))
            } else {
                Round-Money $netSum
            }
            $tol = [decimal]0.03
            $okTotal = ([math]::Abs([decimal]($docTotal - $estDoc)) -le $tol) -or ([math]::Abs([decimal]($docTotal - $estCalc)) -le $tol)
            if (-not $okTotal) {
                Fail 17 (
                    "Total no cuadra: factura " + $docTotal +
                    ", lineas netas " + $netSum +
                    ", estimado " + $estCalc +
                    " (dif " + [math]::Abs([decimal]($docTotal - $estCalc)) +
                    "). No se guarda."
                )
            }
        }

        Write-Host ""
        Write-Host "Guardando factura..."
        Save-SageInvoice $invoice
        Write-Host "OK - Factura guardada"
        Write-InvoiceCard $true $refNumber $cardDate $customer.ID $customer.Name $cardTotal $cardLines ""
        Write-Host ("  Reference: " + $refNumber)
        Write-Host ("  Cliente:   " + $customer.ID)
        Write-Host ("  Sucursal:  " + $sucTxt)
        Write-Host ("  Lineas:    " + $lineNo)
        Write-Host ""
        Write-Host "Verificalo en Sage: Customers & Sales -> Sales Invoices"
        Write-Host "Busca Invoice No. tipo AH060926-R-03355 (dia-mes-ano, sucursal, numero PsKloud)."
        $code = 0
    }
}
catch {
    if ($script:LastAhFail) { Write-Host ("[TRACE] ultimo_fail: " + $script:LastAhFail) }
    elseif ($script:LastAhTrace) { Write-Host ("[TRACE] ultimo_paso: " + $script:LastAhTrace) }
    Write-Host "ERROR: $($_.Exception.Message)"
    if ($_.Exception.InnerException) {
        Write-Host ("  Inner: " + $_.Exception.InnerException.Message)
    }
    Write-Host ("[TRACE] catch fn=RunSageHost paso=try linea= script=" + $_.InvocationInfo.ScriptName + " lineaPS=" + $_.InvocationInfo.ScriptLineNumber)
    $code = 99
}
finally {
    if ($opened) { try { $opened.Close() } catch {} }
    if ($session) { try { $session.End() } catch {} }
    if ($env:AUTOHUB_SAGE_HOST_LOG) { try { Stop-Transcript | Out-Null } catch {} }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

exit $code
