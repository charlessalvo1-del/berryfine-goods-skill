# Reference exact-format builder. Requires Windows, PowerShell, desktop Microsoft
# Excel, and registered Excel COM automation. It never runs as a generic XLSX writer.
param(
    [Parameter(Mandatory=$true)][string]$TemplatePath,
    [Parameter(Mandatory=$true)][string]$PayloadPath,
    [Parameter(Mandatory=$true)][string]$CatalogOutput,
    [Parameter(Mandatory=$true)][string]$ExceptionsOutput,
    [Parameter(Mandatory=$true)][string]$VerificationOutput
)

$ErrorActionPreference = 'Stop'
$xlOpenXMLWorkbook = 51
$xlPatternNone = -4142
$xlSolid = 1
$xlTop = -4160
$xlCenter = -4108
$xlCalculationManual = -4135
$xlPasteFormats = -4122
$yellow = 65535

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Set-TextCell($cell, [object]$value) {
    $text = if ($null -eq $value) { '' } else { [string]$value }
    $cell.NumberFormat = '@'
    if ($text -match '^[=+@-]') { $cell.Value2 = "'$text" } else { $cell.Value2 = $text }
}

function Find-CatalogSheet($book) {
    foreach ($sheet in @($book.Worksheets)) {
        $used = $sheet.UsedRange
        $limit = [Math]::Min(30, $used.Row + $used.Rows.Count - 1)
        for ($row = 1; $row -le $limit; $row++) {
            if ([string]$sheet.Cells.Item($row, 4).Value2 -eq 'LOCATION' -and
                [string]$sheet.Cells.Item($row, 8).Value2 -eq 'HISTORY/INFO') {
                return [pscustomobject]@{ sheet = $sheet; header_row = $row }
            }
        }
    }
    throw 'Unable to find a catalog sheet with LOCATION in D and HISTORY/INFO in H.'
}

$payload = Get-Content -Raw -LiteralPath $PayloadPath | ConvertFrom-Json
$catalogRows = @($payload.catalog_rows)
$exceptionRows = @($payload.exceptions)
if ($catalogRows.Count -lt 1) { throw 'Catalog payload contains no rows.' }
$clientName = [string]$payload.client_name
$catalogBase = if ($clientName.EndsWith(' New Catalog', [StringComparison]::OrdinalIgnoreCase)) { $clientName } else { "$clientName New Catalog" }
$expectedCatalog = "$catalogBase.xlsx"
$expectedExceptions = "$clientName Exceptions.xlsx"
if ([IO.Path]::GetFileName($CatalogOutput) -ne $expectedCatalog) { throw "Catalog output must be named $expectedCatalog" }
if ([IO.Path]::GetFileName($ExceptionsOutput) -ne $expectedExceptions) { throw "Exceptions output must be named $expectedExceptions" }
if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($CatalogOutput)) -ne [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ExceptionsOutput))) { throw 'Catalog and Exceptions workbooks must be in the same client folder.' }
if (Test-Path -LiteralPath $CatalogOutput) { throw "Refusing to overwrite existing output: $CatalogOutput" }
if (Test-Path -LiteralPath $ExceptionsOutput) { throw "Refusing to overwrite existing output: $ExceptionsOutput" }
if (Test-Path -LiteralPath $VerificationOutput) { throw "Refusing to overwrite existing verification: $VerificationOutput" }

$outputDirectory = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($CatalogOutput))
$verificationFullPath = [IO.Path]::GetFullPath($VerificationOutput)
$clientDirectoryPrefix = $outputDirectory.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if ($verificationFullPath.StartsWith($clientDirectoryPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Builder verification must be stored outside the main client folder.' }
[IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($VerificationOutput))) | Out-Null
$catalogTemp = [IO.Path]::Combine($outputDirectory, ".$catalogBase.partial.xlsx")
$exceptionsTemp = [IO.Path]::Combine($outputDirectory, ".$clientName Exceptions.partial.xlsx")
$verificationTemp = "$VerificationOutput.partial"
foreach ($partial in @($catalogTemp, $exceptionsTemp, $verificationTemp)) { if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force } }

$excel = $null; $templateBook = $null; $catalogBook = $null; $exceptionsBook = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false; $excel.DisplayAlerts = $false; $excel.ScreenUpdating = $false; $excel.EnableEvents = $false
    $templateBook = $excel.Workbooks.Open($TemplatePath, 0, $true)
    $excel.Calculation = $xlCalculationManual
    $found = Find-CatalogSheet $templateBook
    $templateSheet = $found.sheet; $headerRow = [int]$found.header_row
    $table = if ($templateSheet.ListObjects.Count -gt 0) { $templateSheet.ListObjects.Item(1) } else { $null }
    $formattedLastRow = if ($table) { $table.Range.Row + $table.Range.Rows.Count - 1 } else { $templateSheet.UsedRange.Row + $templateSheet.UsedRange.Rows.Count - 1 }
    # A client template may preformat hundreds of empty table rows. Retained
    # inventory ends at the last populated SKU in column B, not at the table's
    # formatting boundary.
    $retainedLastRow = $headerRow
    for ($candidate = $headerRow + 1; $candidate -le $formattedLastRow; $candidate++) {
        if (-not [string]::IsNullOrWhiteSpace([string]$templateSheet.Cells.Item($candidate, 2).Value2)) { $retainedLastRow = $candidate }
    }
    if ($retainedLastRow -le $headerRow) { throw 'Template contains no retained data/style row to extend.' }
    $templateHasActionColumn = [string]$templateSheet.Cells.Item($headerRow, 10).Value2 -eq 'RECOMMENDED ACTION'
    $retainedLocationCount = $retainedLastRow - $headerRow
    $retainedLocations = $templateSheet.Range("D$($headerRow + 1)`:D$retainedLastRow").Value2
    $templateBook.SaveCopyAs($catalogTemp)
    # Materialize the template's displayed table style in memory only. The
    # source workbook is read-only and is never saved.
    if ($table) { $table.Unlist() }

    $catalogBook = $excel.Workbooks.Open($catalogTemp, 0, $false)
    $found = Find-CatalogSheet $catalogBook
    $sheet = $found.sheet
    $firstNewRow = $retainedLastRow + 1
    $finalRow = $retainedLastRow + $catalogRows.Count
    # Prefer a preformatted blank row outside historical conditional-format
    # scopes as the style source. Copying a retained sold-status row would make
    # Excel duplicate or extend those rules into new inventory.
    $styleSourceRow = if ($formattedLastRow -gt $retainedLastRow) { $formattedLastRow } else { $retainedLastRow }
    if (-not $templateHasActionColumn) {
        [void]$sheet.Range("I$headerRow`:I$retainedLastRow").Copy($sheet.Range("J$headerRow`:J$retainedLastRow"))
        if ($retainedLastRow -gt $headerRow) { $sheet.Range("J$($headerRow + 1)`:J$retainedLastRow").ClearContents() }
        Set-TextCell $sheet.Cells.Item($headerRow, 10) 'RECOMMENDED ACTION'
    }

    if ($sheet.ListObjects.Count -gt 0) {
        $table = $sheet.ListObjects.Item(1)
        # Unlist without resizing. Shrinking an oversized template table causes
        # Excel to truncate unrelated historical conditional-format ranges.
        $table.Unlist()
    }
    # Restore the exact displayed formats and historical conditional-format
    # scopes from the materialized read-only template snapshot. Include the
    # template's preformatted blank range so Excel's Unlist operation cannot
    # truncate a rule merely because inventory currently ends earlier.
    $retainedFormatLastCol = if ($templateHasActionColumn) { 10 } else { 9 }
    [void]$templateSheet.Range($templateSheet.Cells.Item(1, 1), $templateSheet.Cells.Item($formattedLastRow, $retainedFormatLastCol)).Copy()
    [void]$sheet.Range($sheet.Cells.Item(1, 1), $sheet.Cells.Item($formattedLastRow, $retainedFormatLastCol)).PasteSpecial($xlPasteFormats)
    $excel.CutCopyMode = 0
    $templateBook.Close($false); $templateBook = $null
    if ($sheet.AutoFilterMode) { $sheet.AutoFilterMode = $false }
    $sheet.Range($sheet.Cells.Item($headerRow, 2), $sheet.Cells.Item($finalRow, 10)).AutoFilter() | Out-Null
    # Extend the source row's complete Excel behavior once instead of making a
    # clipboard call per item. Clear values and fills in one bulk operation,
    # then write the validated payload.
    [void]$sheet.Range("A$styleSourceRow`:I$styleSourceRow").Copy($sheet.Range("A$firstNewRow`:I$finalRow"))
    [void]$sheet.Cells.Item($styleSourceRow, 9).Copy($sheet.Range("J$firstNewRow`:J$finalRow"))
    $allNewRows = $sheet.Range("A$firstNewRow`:J$finalRow")
    # Preserve the template's historical conditional-format ranges exactly.
    # Disposition colors below are direct fills, not new conditional rules.
    $allNewRows.ClearContents()
    $allNewRows.Interior.Pattern = $xlPatternNone; $allNewRows.Interior.ColorIndex = $xlPatternNone
    for ($index = 0; $index -lt $catalogRows.Count; $index++) {
        $rowNumber = $firstNewRow + $index; $record = $catalogRows[$index]
        $target = $sheet.Range("A$rowNumber`:J$rowNumber")
        Set-TextCell $sheet.Cells.Item($rowNumber, 2) $record.sku
        Set-TextCell $sheet.Cells.Item($rowNumber, 3) $record.description
        Set-TextCell $sheet.Cells.Item($rowNumber, 4) 'Storage'
        $sheet.Cells.Item($rowNumber, 5).Value2 = [double]$record.quantity; $sheet.Cells.Item($rowNumber, 5).NumberFormat = '0'
        $sheet.Cells.Item($rowNumber, 6).Value2 = [double]$record.estimated_value; $sheet.Cells.Item($rowNumber, 6).NumberFormat = '$#,##0.00'
        Set-TextCell $sheet.Cells.Item($rowNumber, 7) $record.consign_length
        Set-TextCell $sheet.Cells.Item($rowNumber, 8) $record.history_info
        $sheet.Cells.Item($rowNumber, 9).ClearContents()
        Set-TextCell $sheet.Cells.Item($rowNumber, 10) $record.recommended_action
        $target.WrapText = $true; $target.VerticalAlignment = $xlTop; $sheet.Rows.Item($rowNumber).RowHeight = 90
        if ($record.recommended_action -in @('DONATE','REVIEW','CONFIRM DONATION')) { $target.Interior.Pattern = $xlSolid; $target.Interior.Color = $yellow }
    }

    # Extend summary formulas above the header when they end at the old retained row.
    for ($row = 1; $row -lt $headerRow; $row++) {
        for ($col = 1; $col -le 10; $col++) {
            $cell = $sheet.Cells.Item($row, $col)
            $formula = [string]$cell.Formula
            if ($formula.StartsWith('=')) { $cell.Formula = $formula -replace "(?<=[A-Z])$retainedLastRow(?![0-9])", [string]$finalRow }
        }
    }
    $sheet.Columns.Item(8).ColumnWidth = [Math]::Max([double]$sheet.Columns.Item(8).ColumnWidth, 55)
    $sheet.Columns.Item(10).ColumnWidth = 22
    $sheet.PageSetup.PrintArea = $sheet.Range($sheet.Cells.Item(1, 2), $sheet.Cells.Item($finalRow, 10)).Address()
    $sheet.PageSetup.Orientation = 2; $sheet.PageSetup.Zoom = $false; $sheet.PageSetup.FitToPagesWide = 1; $sheet.PageSetup.FitToPagesTall = $false
    $sheet.Calculate()

    # Fail closed on original locations and all new-row rules. catalog_gate.py
    # independently compares every retained value and non-fill style component.
    $currentLocations = $sheet.Range("D$($headerRow + 1)`:D$retainedLastRow").Value2
    for ($offset = 1; $offset -le $retainedLocationCount; $offset++) {
        $row = $headerRow + $offset
        $expectedLocation = if ($retainedLocationCount -eq 1) { [string]$retainedLocations } else { [string]$retainedLocations[$offset, 1] }
        $actualLocation = if ($retainedLocationCount -eq 1) { [string]$currentLocations } else { [string]$currentLocations[$offset, 1] }
        if ($actualLocation -ne $expectedLocation) { throw "Retained LOCATION changed at row $row." }
    }
    for ($index = 0; $index -lt $catalogRows.Count; $index++) {
        $rowNumber = $firstNewRow + $index; $record = $catalogRows[$index]
        $target = $sheet.Range("A$rowNumber`:J$rowNumber")
        if ([string]$sheet.Cells.Item($rowNumber, 4).Value2 -ne 'Storage') { throw "New LOCATION is not Storage at row $rowNumber." }
        if ([string]$sheet.Cells.Item($rowNumber, 8).Value2 -ne [string]$record.history_info) { throw "HISTORY/INFO mismatch at row $rowNumber." }
        if ($null -ne $sheet.Cells.Item($rowNumber, 9).Value2) { throw "Column I is not blank at row $rowNumber." }
        if ([string]$sheet.Cells.Item($rowNumber, 10).Value2 -ne [string]$record.recommended_action) { throw "RECOMMENDED ACTION mismatch at row $rowNumber." }
        $yellowExpected = $record.recommended_action -in @('DONATE','REVIEW','CONFIRM DONATION')
        $displayPattern = $target.DisplayFormat.Interior.Pattern
        $displayColor = $target.DisplayFormat.Interior.Color
        if ($displayPattern -is [DBNull] -or $displayColor -is [DBNull]) { throw "New row $rowNumber does not have a uniform displayed fill across A:J." }
        if ($yellowExpected -and ([int]$displayPattern -ne $xlSolid -or [int]$displayColor -ne $yellow)) { throw "Expected displayed yellow fill across row $rowNumber." }
        if (-not $yellowExpected -and [int]$displayPattern -ne $xlPatternNone) { throw "SELL row has a displayed fill at row $rowNumber." }
    }
    $catalogBook.Save(); $catalogBook.Close($false); $catalogBook = $null

    $exceptionsBook = $excel.Workbooks.Add()
    while ($exceptionsBook.Worksheets.Count -gt 1) { $exceptionsBook.Worksheets.Item($exceptionsBook.Worksheets.Count).Delete() }
    $exceptionsSheet = $exceptionsBook.Worksheets.Item(1); $exceptionsSheet.Name = 'Exceptions'
    $headers = @('SKU','Stable Item ID','Photo References','Description','Exception Category','Issue','Required Action','Status','Resolution Notes','Resolution Date')
    for ($col=1; $col -le 10; $col++) { Set-TextCell $exceptionsSheet.Cells.Item(1,$col) $headers[$col-1] }
    for ($index=0; $index -lt $exceptionRows.Count; $index++) {
        $record=$exceptionRows[$index]; $values=@($record.sku,$record.item_id,$record.photo_references,$record.description,$record.exception_category,$record.issue,$record.required_action,$record.status,$record.resolution_notes,$record.resolution_date)
        for ($col=1; $col -le 10; $col++) { Set-TextCell $exceptionsSheet.Cells.Item($index+2,$col) $values[$col-1] }
    }
    $lastExceptionRow=[Math]::Max(1,1+$exceptionRows.Count)
    $headerRange=$exceptionsSheet.Range('A1:J1'); $headerRange.Font.Bold=$true; $headerRange.Font.Color=16777215; $headerRange.Interior.Pattern=$xlSolid; $headerRange.Interior.Color=3169331; $headerRange.HorizontalAlignment=$xlCenter
    $used=$exceptionsSheet.Range("A1:J$lastExceptionRow"); $used.WrapText=$true; $used.VerticalAlignment=$xlTop; $used.AutoFilter() | Out-Null
    $widths=@(10,21,35,38,28,48,48,12,28,15); for($col=1;$col -le 10;$col++){$exceptionsSheet.Columns.Item($col).ColumnWidth=[double]$widths[$col-1]}
    $exceptionsSheet.Rows.Item(1).RowHeight=[double]30; for($row=2;$row -le $lastExceptionRow;$row++){$exceptionsSheet.Rows.Item($row).RowHeight=[double]75}
    $exceptionsSheet.Activate(); $excel.ActiveWindow.SplitRow=1; $excel.ActiveWindow.FreezePanes=$true
    $exceptionsSheet.PageSetup.PrintArea=$exceptionsSheet.Range("A1:J$lastExceptionRow").Address(); $exceptionsSheet.PageSetup.Orientation=2; $exceptionsSheet.PageSetup.Zoom=$false; $exceptionsSheet.PageSetup.FitToPagesWide=1; $exceptionsSheet.PageSetup.FitToPagesTall=$false
    $exceptionsBook.SaveAs($exceptionsTemp,$xlOpenXMLWorkbook); $exceptionsBook.Close($false); $exceptionsBook=$null
    $verification=[ordered]@{version=1;status='PASS';client_name=$clientName;intake_id=[string]$payload.intake_id;template_sha256=Get-Sha256 $TemplatePath;payload_sha256=Get-Sha256 $PayloadPath;catalog_sha256=Get-Sha256 $catalogTemp;exceptions_sha256=Get-Sha256 $exceptionsTemp;retained_last_row=$retainedLastRow;first_new_row=$firstNewRow;final_row=$finalRow;new_item_count=$catalogRows.Count;exception_count=$exceptionRows.Count;retained_locations_preserved=$true;retained_displayed_fills_preserved=$true;retained_fill_method='excel-materialized-format-snapshot';historical_action_column_preserved=$templateHasActionColumn;new_location='Storage';actions=@('SELL','DONATE','REVIEW','CONFIRM DONATION')}
    $verification | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $verificationTemp -Encoding utf8
    $catalogPublished=$false; $exceptionsPublished=$false; $verificationPublished=$false
    try {
        Move-Item -LiteralPath $catalogTemp -Destination $CatalogOutput; $catalogPublished=$true
        Move-Item -LiteralPath $exceptionsTemp -Destination $ExceptionsOutput; $exceptionsPublished=$true
        Move-Item -LiteralPath $verificationTemp -Destination $VerificationOutput; $verificationPublished=$true
    }
    catch {
        if ($verificationPublished -and (Test-Path -LiteralPath $VerificationOutput)) { Remove-Item -LiteralPath $VerificationOutput -Force }
        if ($exceptionsPublished -and (Test-Path -LiteralPath $ExceptionsOutput)) { Remove-Item -LiteralPath $ExceptionsOutput -Force }
        if ($catalogPublished -and (Test-Path -LiteralPath $CatalogOutput)) { Remove-Item -LiteralPath $CatalogOutput -Force }
        throw
    }
    $verification | ConvertTo-Json -Depth 5
}
finally {
    if ($templateBook) { try { $templateBook.Close($false) } catch {} }; if ($catalogBook) { try { $catalogBook.Close($false) } catch {} }; if ($exceptionsBook) { try { $exceptionsBook.Close($false) } catch {} }; if ($excel) { try { $excel.Quit() } catch {} }
    foreach ($object in @($exceptionsBook,$catalogBook,$templateBook,$excel)) { if ($object) { try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($object) } catch {} } }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
    foreach ($partial in @($catalogTemp,$exceptionsTemp,$verificationTemp)) { if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force } }
}
