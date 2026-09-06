# Sage 50 SDK host for Windows Smart App Control.
# Unsigned csc.exe output is blocked (WinError 4551). This runs inside
# signed 32-bit powershell.exe and only loads Sage's own DLLs.
param(
    [Parameter(Mandatory = $true)][string]$Company,
    [Parameter(Mandatory = $true)][string]$AppIdFile,
    [string]$SampleJson = "",
    [string]$CustomerId = "",
    [string]$CustomerName = "",
    [switch]$AuthOnly
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SampleJson) {
    $SampleJson = Join-Path $scriptDir "sample_invoice.json"
}

function Fail([int]$code, [string]$msg) {
    Write-Host "ERROR: $msg"
    exit $code
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

function New-SageCustomer($company, [string]$id, [string]$name, [string]$ruc, $template) {
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
    Write-Host ("  Guardando cliente nuevo: " + $safeId + " | " + $safeName)
    Save-SageEntity $cust
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
        foreach ($c in $customers) {
            $cn = Normalize-Person $c.Name
            $cid = Normalize-Person $c.ID
            if (($cn -and ($cn.Contains($want) -or $want.Contains($cn))) -or
                ($cid -and ($cid.Contains($want) -or $want.Contains($cid)))) {
                Write-Host ("  Match por nombre/ID parcial: " + $c.ID + " | " + $c.Name)
                return $c
            }
        }
    }

    foreach ($id in $idSet) {
        $compact = $id -replace "[^0-9A-Za-z]", ""
        if ($compact.Length -lt 4) { continue }
        foreach ($c in $customers) {
            $cid = ($c.ID -replace "[^0-9A-Za-z]", "")
            if ($cid -and $cid.IndexOf($compact, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                Write-Host ("  Match por codigo compacto: " + $c.ID + " | " + $c.Name)
                return $c
            }
        }
    }

    $skipLast = @("SA", "SAS", "SRL", "INC", "LTDA", "CIA", "CO")
    foreach ($want in $nameSet) {
        $parts = @($want.Split(" ") | Where-Object { $_ })
        if ($parts.Count -lt 2) { continue }
        $last = $parts[-1]
        if ($last.Length -lt 4 -or $skipLast -contains $last) { continue }
        $byId = @{}
        foreach ($c in $customers) {
            $cn = Normalize-Person $c.Name
            $cparts = @($cn.Split(" ") | Where-Object { $_ })
            if ($cparts.Count -ge 1 -and $cparts[-1] -eq $last) {
                $byId[$c.ID] = $c
            }
        }
        if ($byId.Count -eq 1) {
            $one = @($byId.Values)[0]
            Write-Host ("  Match por apellido unico (" + $last + "): " + $one.ID + " | " + $one.Name)
            return $one
        }
        if ($byId.Count -gt 1) {
            Write-Host ("  AVISO apellido " + $last + " coincide con " + $byId.Count + " clientes Sage; no se adivina.")
            foreach ($h in $byId.Values) {
                Write-Host ("    " + $h.ID + " | " + $h.Name)
            }
        }
    }

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

function Get-SageRefPrefix([string]$sucursal) {
    $s = if ($sucursal) { $sucursal.ToUpperInvariant() } else { "" }
    if ($s -match "CORONADO") { return "AHC" }
    if ($s -match "RIO ABAJO") { return "AHR" }
    if ($s -match "ADI") { return "AHA" }
    return "AH"
}

function Normalize-CompanyName([string]$value) {
    return [regex]::Replace($value.Trim(), "\s+", " ")
}

Write-Host "Auto-Hub - envio a Sage 50"
Write-Host "Empresa objetivo: $Company"
Write-Host "Application ID: (configurado, $($appId.Length) chars)"
Write-Host "Modo: $(if ($AuthOnly) { 'autorizar Always Allow' } else { 'escritura' })"
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
    Write-Host "Sesion iniciada: $($session.SessionActive)"

    $wanted = Normalize-CompanyName $Company
    $companyId = $null
    Write-Host "Companias registradas en Sage:"
    foreach ($id in $session.CompanyList()) {
        Write-Host ("  - " + $id.CompanyName)
        if ((Normalize-CompanyName $id.CompanyName) -eq $wanted) {
            $companyId = $id
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
    else {
        $records = @(Get-InvoiceRecords $SampleJson)
        if ($records.Count -lt 1) {
            Fail 15 "sample sin lineas de factura: $SampleJson"
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
        $prefix = Get-SageRefPrefix $sucTxt
        $refNumber = $prefix + (Get-Date).ToString("yyyyMMddHHmmss")
        if ($refNumber.Length -gt 20) { $refNumber = $refNumber.Substring(0, 20) }
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
            try {
                $created = New-SageCustomer $opened $wantId $wantName $ruc $template
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

        $salesAcctRef = $null
        try { $salesAcctRef = $customer.UsualSalesAccountReference } catch {
            Write-Host ("AVISO UsualSalesAccountReference: " + $_.Exception.Message)
        }
        if ($null -eq $salesAcctRef) {
            Fail 4 ($customer.ID + " no tiene UsualSalesAccountReference (GL ventas).")
        }
        Write-Host ("  UsualSalesAccountReference: " + $salesAcctRef)

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

        Set-SageProp $invoice "Date" $fechaEmision | Out-Null
        Set-SageProp $invoice "TransactionDate" $fechaEmision | Out-Null
        Set-SageProp $invoice "DatePosted" $fechaEmision | Out-Null
        Set-SageProp $invoice "ShipDate" $fechaEmision | Out-Null
        Set-SageProp $invoice "ReferenceNumber" $refNumber | Out-Null
        Set-SageProp $invoice "InvoiceNumber" $refNumber | Out-Null
        Set-SageProp $invoice "Number" $refNumber | Out-Null
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
        foreach ($rec in $records) {
            $lineNo++
            $line = Add-SageInvoiceLine $invoice $opened
            if ($null -eq $line) {
                Fail 6 ("no se pudo crear linea " + $lineNo)
            }
            $desc = Get-RecordText $rec "descripcion"
            if (-not $desc) { $desc = "Linea $lineNo" }
            $suc = Get-RecordText $rec "sucursal"
            if ($suc) { $desc = "[" + $suc + "] " + $desc }
            if ($createdNewCustomer -and $lineNo -eq 1) {
                $desc = "[CLIENTE NUEVO] " + $desc
            }
            $qty = Get-RecordDecimal $rec "cantidad" 1
            $price = Get-RecordDecimal $rec "precio_unitario" 0
            $amount = Get-RecordDecimal $rec "total_linea" ($qty * $price)
            Set-SageProp $line "Description" $desc | Out-Null
            Set-SageProp $line "Quantity" $qty | Out-Null
            Set-SageProp $line "QuantitySold" $qty | Out-Null
            Set-SageProp $line "UnitPrice" $price | Out-Null
            Set-SageProp $line "Amount" $amount | Out-Null
            Set-SageProp $line "AccountReference" $salesAcctRef | Out-Null
            Set-SageProp $line "GLAccountReference" $salesAcctRef | Out-Null
            Set-SageProp $line "IsInventory" $false | Out-Null
            $short = $desc
            if ($short.Length -gt 60) { $short = $short.Substring(0, 57) + "..." }
            Write-Host ("  Linea " + $lineNo + ": qty=" + $qty + " price=" + $price + " | " + $short)
        }

        Write-Host ""
        Write-Host "Guardando factura..."
        Save-SageInvoice $invoice
        Write-Host "OK - Factura guardada"
        Write-Host ("  Reference: " + $refNumber)
        Write-Host ("  Cliente:   " + $customer.ID)
        Write-Host ("  Sucursal:  " + $sucTxt)
        Write-Host ("  Lineas:    " + $records.Count)
        Write-Host ""
        Write-Host "Verificalo en Sage: Customers & Sales -> Sales Invoices"
        Write-Host "Busca Invoice No. con AHC (Coronado), AHR (Rio Abajo) o AHA (ADI Supply)."
        $code = 0
    }
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    if ($_.Exception.InnerException) {
        Write-Host ("  Inner: " + $_.Exception.InnerException.Message)
    }
    $code = 99
}
finally {
    if ($opened) { try { $opened.Close() } catch {} }
    if ($session) { try { $session.End() } catch {} }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

exit $code
