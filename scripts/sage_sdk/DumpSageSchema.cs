/*
 * SOLO LECTURA - inventariar campos/valores de la empresa Sage real
 * para mapear PsKloud -> Sage.
 *
 * Empresa por defecto: LYL CONSTRUCTIONS SUPPLY INC 2025
 * Sale a: dump\schema_summary.txt, customers.json, invoices.json, types.json
 */
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using Sage.Peachtree.API;

namespace AutoHub.SageSchemaDump
{
    internal static class Program
    {
        private const string DefaultCompany = "LYL CONSTRUCTIONS SUPPLY INC 2025";
        private const string ProbeVersion = "2026-08-17-schema-b";
        private const int MaxCustomers = 80;
        private const int MaxInvoices = 12;
        private const int MaxAccounts = 60;
        private const int MaxLinesPerInvoice = 30;

        private static string NormalizeCompanyName(string value)
        {
            return Regex.Replace(value.Trim(), @"\s+", " ");
        }

        private static bool CompanyNamesEqual(string a, string b)
        {
            return string.Equals(
                NormalizeCompanyName(a),
                NormalizeCompanyName(b),
                StringComparison.OrdinalIgnoreCase
            );
        }

        private static int Main(string[] args)
        {
            try
            {
                Sage.Peachtree.API.Resolver.AssemblyInitializer.Initialize();
                Console.WriteLine("AssemblyInitializer.Initialize() OK");
            }
            catch (Exception ex)
            {
                Console.WriteLine("AVISO AssemblyInitializer: " + ex.Message);
                try { Sage.Peachtree.API.AssemblyInitializer.Initialize(); }
                catch { }
            }

            var targetName = args.Length > 0 ? args[0] : DefaultCompany;
            var appId = Environment.GetEnvironmentVariable("SAGE_APP_ID") ?? "";
            if (args.Length > 1)
                appId = args[1];

            Console.WriteLine("Auto-Hub - DUMP SCHEMA Sage 50 SDK (SOLO LECTURA)");
            Console.WriteLine("VERSION: " + ProbeVersion);
            Console.WriteLine("Empresa: " + targetName);
            Console.WriteLine("NO escribe ni modifica datos.");
            if (string.IsNullOrWhiteSpace(appId))
            {
                Console.WriteLine("ERROR: falta Application ID (app_id.txt).");
                WaitBeforeExit();
                return 13;
            }
            Console.WriteLine("Application ID: (configurado, " + appId.Length + " chars)");
            Console.WriteLine();

            var outDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "dump");
            Directory.CreateDirectory(outDir);

            PeachtreeSession session = null;
            Company company = null;
            var summary = new StringBuilder();
            summary.AppendLine("Auto-Hub Sage schema dump " + ProbeVersion);
            summary.AppendLine("Empresa: " + targetName);
            summary.AppendLine("Fecha dump: " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
            summary.AppendLine();

            try
            {
                session = new PeachtreeSession();
                session.Begin(appId);
                Console.WriteLine("Sesion iniciada: " + session.SessionActive);

                var companies = session.CompanyList();
                Console.WriteLine("Companias en Sage:");
                foreach (CompanyIdentifier c in companies)
                    Console.WriteLine("  - " + c.CompanyName);
                Console.WriteLine();

                var companyId = companies.Cast<CompanyIdentifier>()
                    .FirstOrDefault(c => CompanyNamesEqual(c.CompanyName, targetName));
                if (companyId == null)
                {
                    Console.WriteLine("ERROR: no se encontro la empresa: " + targetName);
                    Console.WriteLine("Copia el nombre EXACTO de la barra de Sage.");
                    WaitBeforeExit();
                    return 1;
                }

                var auth = WaitForGrant(session, companyId, targetName);
                if (auth != AuthorizationResult.Granted)
                {
                    Console.WriteLine("ERROR: sin autorizacion Granted. Estado: " + auth);
                    WaitBeforeExit();
                    return 2;
                }

                company = session.Open(companyId);
                Console.WriteLine("Empresa abierta via SDK (lectura).");
                Console.WriteLine();

                var types = new Dictionary<string, object>();
                var factories = company.Factories;
                types["Factories"] = DescribeType(factories.GetType(), includeMethods: true);

                // --- Customers ---
                Console.WriteLine("Cargando clientes (max " + MaxCustomers + ")...");
                var customersOut = new List<Dictionary<string, object>>();
                Customer sampleCustomer = null;
                try
                {
                    var clist = company.Factories.CustomerFactory.List();
                    clist.Load();
                    int n = 0;
                    foreach (Customer c in clist)
                    {
                        if (sampleCustomer == null) sampleCustomer = c;
                        customersOut.Add(SnapshotEntity(c, new[]
                        {
                            "ID", "Name", "IsInactive", "IsProspect",
                            "UsualSalesAccountReference", "CashAccountReference",
                            "SalesTaxCodeReference", "Terms", "Key",
                            "Email", "PhoneNumber", "Category", "CustomerType"
                        }));
                        if (++n >= MaxCustomers) break;
                    }
                    summary.AppendLine("Clientes muestreados: " + customersOut.Count);
                    Console.WriteLine("  -> " + customersOut.Count + " clientes");
                    if (sampleCustomer != null)
                        types["Customer"] = DescribeType(sampleCustomer.GetType(), includeMethods: false);
                }
                catch (Exception ex)
                {
                    Console.WriteLine("AVISO clientes: " + ex.Message);
                    summary.AppendLine("ERROR clientes: " + ex.Message);
                }

                // --- Accounts ---
                Console.WriteLine("Cargando cuentas GL (max " + MaxAccounts + ")...");
                var accountsOut = new List<Dictionary<string, object>>();
                try
                {
                    object acctFactory = GetProp(factories, "AccountFactory");
                    if (acctFactory != null)
                    {
                        object list = InvokeMethod(acctFactory, "List");
                        if (list != null)
                        {
                            InvokeMethod(list, "Load");
                            int n = 0;
                            foreach (object a in (IEnumerable)list)
                            {
                                accountsOut.Add(SnapshotEntity(a, new[]
                                {
                                    "ID", "Description", "AccountType", "IsInactive", "Key"
                                }));
                                if (++n >= MaxAccounts) break;
                            }
                        }
                    }
                    summary.AppendLine("Cuentas muestreadas: " + accountsOut.Count);
                    Console.WriteLine("  -> " + accountsOut.Count + " cuentas");
                    if (accountsOut.Count > 0)
                    {
                        // type from first live object if possible
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine("AVISO cuentas: " + ex.Message);
                    summary.AppendLine("ERROR cuentas: " + ex.Message);
                }

                // --- Sales invoices ---
                Console.WriteLine("Cargando facturas (max " + MaxInvoices + ")...");
                var invoicesOut = new List<Dictionary<string, object>>();
                object sampleInvoice = null;
                object sampleLine = null;
                try
                {
                    object invFactory = GetProp(factories, "SalesInvoiceFactory");
                    if (invFactory == null)
                    {
                        Console.WriteLine("AVISO: no hay SalesInvoiceFactory");
                        summary.AppendLine("SalesInvoiceFactory: ausente");
                    }
                    else
                    {
                        types["SalesInvoiceFactory"] = DescribeType(invFactory.GetType(), includeMethods: true);
                        object list = InvokeMethod(invFactory, "List");
                        if (list != null)
                        {
                            InvokeMethod(list, "Load");
                            int n = 0;
                            foreach (object inv in (IEnumerable)list)
                            {
                                if (sampleInvoice == null) sampleInvoice = inv;
                                var snap = SnapshotEntity(inv, new[]
                                {
                                    "ReferenceNumber", "InvoiceNumber", "Number",
                                    "Date", "TransactionDate", "DateDue", "ShipDate",
                                    "CustomerReference", "AccountReference",
                                    "Amount", "AmountDue", "SalesTaxCodeReference",
                                    "Note", "Memo", "Key", "IsPaid", "Status"
                                });

                                var lines = new List<Dictionary<string, object>>();
                                try
                                {
                                    // En esta API US las lineas viven en ApplyToSalesLines
                                    object lineColl = GetProp(inv, "ApplyToSalesLines")
                                        ?? GetProp(inv, "SalesLines")
                                        ?? GetProp(inv, "Lines")
                                        ?? GetProp(inv, "InvoiceLines");

                                    if (lineColl != null)
                                    {
                                        // Algunas colecciones requieren Load()
                                        try { InvokeMethod(lineColl, "Load"); } catch { }

                                        snap["_lines_collection"] = lineColl.GetType().FullName;
                                        DumpTypeMembersOnce(lineColl.GetType(), "SalesInvoiceSalesLineCollection", types);

                                        int ln = 0;
                                        if (lineColl is IEnumerable)
                                        {
                                            foreach (object line in (IEnumerable)lineColl)
                                            {
                                                if (line == null) continue;
                                                if (sampleLine == null)
                                                {
                                                    sampleLine = line;
                                                    types["SalesInvoiceLine"] = DescribeType(line.GetType(), includeMethods: true);
                                                }
                                                lines.Add(SnapshotEntity(line, new[]
                                                {
                                                    "Description", "Quantity", "QuantitySold",
                                                    "UnitPrice", "Amount", "AccountReference",
                                                    "InventoryItemReference", "JobReference",
                                                    "SalesTaxType", "TaxType", "TaxAmount",
                                                    "StockingQuantity", "UnitOfMeasure"
                                                }));
                                                if (++ln >= MaxLinesPerInvoice) break;
                                            }
                                        }

                                        // Fallback: Count / indexer
                                        if (lines.Count == 0)
                                        {
                                            object countObj = GetProp(lineColl, "Count");
                                            int count = 0;
                                            if (countObj != null)
                                                int.TryParse(Convert.ToString(countObj), out count);
                                            snap["_lines_count_prop"] = count;
                                            for (int i = 0; i < count && i < MaxLinesPerInvoice; i++)
                                            {
                                                object line = null;
                                                try
                                                {
                                                    var idx = lineColl.GetType().GetProperty("Item");
                                                    if (idx != null)
                                                        line = idx.GetValue(lineColl, new object[] { i });
                                                }
                                                catch { }
                                                if (line == null) continue;
                                                if (sampleLine == null) sampleLine = line;
                                                lines.Add(SnapshotEntity(line, new[]
                                                {
                                                    "Description", "Quantity", "QuantitySold",
                                                    "UnitPrice", "Amount", "AccountReference",
                                                    "InventoryItemReference", "JobReference",
                                                    "SalesTaxType", "TaxType", "TaxAmount"
                                                }));
                                            }
                                        }
                                    }
                                    else
                                    {
                                        snap["_lines_collection"] = "(null)";
                                    }
                                }
                                catch (Exception lex)
                                {
                                    snap["_lines_error"] = lex.Message;
                                    if (lex.InnerException != null)
                                        snap["_lines_inner"] = lex.InnerException.Message;
                                }
                                snap["lines"] = lines;
                                snap["_line_count"] = lines.Count;
                                if (lines.Count > 0)
                                    Console.WriteLine("    factura " +
                                        (snap.ContainsKey("ReferenceNumber") ? snap["ReferenceNumber"] : "?") +
                                        " -> " + lines.Count + " lineas");
                                invoicesOut.Add(snap);
                                if (++n >= MaxInvoices) break;
                            }
                        }
                    }
                    summary.AppendLine("Facturas muestreadas: " + invoicesOut.Count);
                    int withLines = invoicesOut.Count(x =>
                    {
                        object lc;
                        return x.TryGetValue("_line_count", out lc) && Convert.ToInt32(lc) > 0;
                    });
                    summary.AppendLine("Facturas con lineas cargadas: " + withLines);
                    Console.WriteLine("  -> " + invoicesOut.Count + " facturas (" + withLines + " con lineas)");
                    if (sampleInvoice != null)
                        types["SalesInvoice"] = DescribeType(sampleInvoice.GetType(), includeMethods: true);
                    if (sampleLine != null && !types.ContainsKey("SalesInvoiceLine"))
                        types["SalesInvoiceLine"] = DescribeType(sampleLine.GetType(), includeMethods: true);
                }
                catch (Exception ex)
                {
                    Console.WriteLine("AVISO facturas: " + ex.Message);
                    summary.AppendLine("ERROR facturas: " + ex.Message);
                    if (ex.InnerException != null)
                        summary.AppendLine("  Inner: " + ex.InnerException.Message);
                }

                summary.AppendLine();
                summary.AppendLine("=== Campos con valor en facturas muestreadas ===");
                AppendFilledFieldStats(summary, invoicesOut, "invoice");
                summary.AppendLine();
                summary.AppendLine("=== Campos con valor en lineas de factura ===");
                var allLines = new List<Dictionary<string, object>>();
                foreach (var inv in invoicesOut)
                {
                    object linesObj;
                    if (!inv.TryGetValue("lines", out linesObj)) continue;
                    var ll = linesObj as List<Dictionary<string, object>>;
                    if (ll != null) allLines.AddRange(ll);
                }
                AppendFilledFieldStats(summary, allLines, "line");
                summary.AppendLine();
                summary.AppendLine("=== Campos con valor en clientes muestreados ===");
                AppendFilledFieldStats(summary, customersOut, "customer");

                var ser = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
                File.WriteAllText(Path.Combine(outDir, "customers.json"), ser.Serialize(customersOut));
                File.WriteAllText(Path.Combine(outDir, "accounts.json"), ser.Serialize(accountsOut));
                File.WriteAllText(Path.Combine(outDir, "invoices.json"), ser.Serialize(invoicesOut));
                File.WriteAllText(Path.Combine(outDir, "types.json"), ser.Serialize(types));
                File.WriteAllText(Path.Combine(outDir, "schema_summary.txt"), summary.ToString());

                // Plantilla cruce clientes Sage (rellenar pskloud_codigo / pskloud_nombre)
                WriteCustomerCrosswalkCsv(Path.Combine(outDir, "customers_crosswalk_template.csv"), customersOut);

                Console.WriteLine();
                Console.WriteLine("OK - Dump escrito en:");
                Console.WriteLine("  " + outDir);
                Console.WriteLine("  - schema_summary.txt");
                Console.WriteLine("  - customers.json");
                Console.WriteLine("  - accounts.json");
                Console.WriteLine("  - invoices.json");
                Console.WriteLine("  - types.json");
                Console.WriteLine("  - customers_crosswalk_template.csv");
                Console.WriteLine();
                Console.WriteLine(summary.ToString());
                WaitBeforeExit();
                return 0;
            }
            catch (Exception ex)
            {
                Console.WriteLine("ERROR: " + ex.Message);
                if (ex.InnerException != null)
                    Console.WriteLine("  Inner: " + ex.InnerException.Message);
                WaitBeforeExit();
                return 99;
            }
            finally
            {
                if (company != null)
                {
                    try { company.Close(); } catch { }
                }
                if (session != null)
                {
                    try { session.End(); } catch { }
                }
            }
        }

        private static void DumpTypeMembersOnce(
            Type type, string key, Dictionary<string, object> types)
        {
            if (type == null || types == null) return;
            if (types.ContainsKey(key)) return;
            types[key] = DescribeType(type, includeMethods: true);
        }

        private static void WriteCustomerCrosswalkCsv(
            string path, List<Dictionary<string, object>> customers)
        {
            var sb = new StringBuilder();
            sb.AppendLine("sage_customer_id,sage_customer_name,usual_sales_account,cash_account,terms,payment_method,pskloud_cliente_codigo,pskloud_cliente_nombre,notes");
            foreach (var c in customers)
            {
                sb.Append(Csv(GetDictStr(c, "ID"))).Append(',');
                sb.Append(Csv(GetDictStr(c, "Name"))).Append(',');
                sb.Append(Csv(GetDictStr(c, "UsualSalesAccountReference"))).Append(',');
                sb.Append(Csv(GetDictStr(c, "CashAccountReference"))).Append(',');
                sb.Append(Csv(GetDictStr(c, "Terms"))).Append(',');
                sb.Append(Csv(GetDictStr(c, "PaymentMethod"))).Append(',');
                sb.Append(','); // pskloud_cliente_codigo - rellenar
                sb.Append(','); // pskloud_cliente_nombre - rellenar
                sb.AppendLine("");
            }
            File.WriteAllText(path, sb.ToString(), Encoding.UTF8);
        }

        private static string GetDictStr(Dictionary<string, object> d, string key)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v) || v == null) return "";
            return Convert.ToString(v, CultureInfo.InvariantCulture) ?? "";
        }

        private static string Csv(string s)
        {
            if (s == null) s = "";
            if (s.IndexOfAny(new[] { ',', '"', '\n', '\r' }) >= 0)
                return "\"" + s.Replace("\"", "\"\"") + "\"";
            return s;
        }

        private static void AppendFilledFieldStats(
            StringBuilder summary,
            List<Dictionary<string, object>> rows,
            string label)
        {
            if (rows == null || rows.Count == 0)
            {
                summary.AppendLine("(sin " + label + ")");
                return;
            }
            var counts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (var row in rows)
            {
                foreach (var kv in row)
                {
                    if (kv.Key.StartsWith("_") || kv.Key == "lines") continue;
                    if (IsEmpty(kv.Value)) continue;
                    if (!counts.ContainsKey(kv.Key)) counts[kv.Key] = 0;
                    counts[kv.Key]++;
                }
            }
            foreach (var kv in counts.OrderByDescending(x => x.Value).ThenBy(x => x.Key))
                summary.AppendLine("  " + kv.Key + ": " + kv.Value + "/" + rows.Count);
        }

        private static bool IsEmpty(object v)
        {
            if (v == null) return true;
            var s = Convert.ToString(v, CultureInfo.InvariantCulture);
            return string.IsNullOrWhiteSpace(s) || s == "(null)";
        }

        private static Dictionary<string, object> SnapshotEntity(object entity, string[] preferred)
        {
            var d = new Dictionary<string, object>();
            if (entity == null) return d;

            var type = entity.GetType();
            var preferredSet = new HashSet<string>(preferred ?? new string[0], StringComparer.OrdinalIgnoreCase);

            foreach (var name in preferred ?? new string[0])
            {
                d[name] = SafeValue(GetProp(entity, name));
            }

            // Props publicas extras (hasta 30) no listadas
            int extra = 0;
            foreach (var p in type.GetProperties(BindingFlags.Instance | BindingFlags.Public)
                .OrderBy(x => x.Name))
            {
                if (preferredSet.Contains(p.Name)) continue;
                if (p.GetIndexParameters().Length > 0) continue;
                if (extra >= 30) break;
                try
                {
                    var val = p.GetValue(entity, null);
                    // Omitir colecciones grandes salvo nombre util
                    if (val is IEnumerable && !(val is string) && !IsSimpleEnumerable(val))
                    {
                        d[p.Name] = "(collection:" + val.GetType().Name + ")";
                    }
                    else
                    {
                        d[p.Name] = SafeValue(val);
                    }
                    extra++;
                }
                catch (Exception ex)
                {
                    d[p.Name] = "(error:" + ex.GetType().Name + ")";
                    extra++;
                }
            }

            d["_type"] = type.FullName;
            return d;
        }

        private static bool IsSimpleEnumerable(object val)
        {
            // EntityReference etc. no son "simples"; dejamos ToString via SafeValue
            return false;
        }

        private static object SafeValue(object val)
        {
            if (val == null) return null;
            try
            {
                if (val is DateTime)
                    return ((DateTime)val).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
                if (val is decimal || val is double || val is float || val is int || val is long)
                    return Convert.ToString(val, CultureInfo.InvariantCulture);
                if (val is bool || val is string)
                    return val;
                var s = val.ToString();
                if (s != null && s.Length > 200) s = s.Substring(0, 200) + "...";
                return s;
            }
            catch
            {
                return "(unreadable)";
            }
        }

        private static Dictionary<string, object> DescribeType(Type type, bool includeMethods)
        {
            var d = new Dictionary<string, object>();
            d["FullName"] = type.FullName;
            d["Assembly"] = type.Assembly.GetName().Name;
            d["Properties"] = type.GetProperties(BindingFlags.Instance | BindingFlags.Public)
                .Where(p => p.GetIndexParameters().Length == 0)
                .OrderBy(p => p.Name)
                .Select(p => p.Name + ":" + p.PropertyType.Name)
                .ToArray();
            if (includeMethods)
            {
                d["Methods"] = type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly)
                    .Where(m => !m.IsSpecialName)
                    .Select(m => m.Name + "(" + string.Join(",", m.GetParameters().Select(p => p.ParameterType.Name).ToArray()) + ")")
                    .Distinct()
                    .OrderBy(s => s)
                    .Take(60)
                    .ToArray();
            }
            return d;
        }

        private static object GetProp(object obj, string name)
        {
            if (obj == null) return null;
            try
            {
                var p = obj.GetType().GetProperty(name,
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase);
                if (p == null) return null;
                return p.GetValue(obj, null);
            }
            catch
            {
                return null;
            }
        }

        private static object InvokeMethod(object obj, string name, params object[] args)
        {
            if (obj == null) return null;
            try
            {
                Type[] types = args == null || args.Length == 0
                    ? Type.EmptyTypes
                    : Array.ConvertAll(args, a => a == null ? typeof(object) : a.GetType());
                var m = obj.GetType().GetMethod(name, types)
                    ?? obj.GetType().GetMethods()
                        .FirstOrDefault(x => x.Name == name && x.GetParameters().Length == (args == null ? 0 : args.Length));
                if (m == null) return null;
                return m.Invoke(obj, args ?? new object[0]);
            }
            catch
            {
                return null;
            }
        }

        private static AuthorizationResult WaitForGrant(
            PeachtreeSession session, CompanyIdentifier companyId, string companyName)
        {
            Console.WriteLine("Solicitando acceso...");
            var auth = session.RequestAccess(companyId);
            Console.WriteLine("Autorizacion: " + auth);

            if (auth == AuthorizationResult.Pending)
            {
                Console.WriteLine();
                Console.WriteLine("=== ACCION EN SAGE ===");
                Console.WriteLine("1. Cierra la empresa si hace falta (File > Close Company)");
                Console.WriteLine("2. Abre: " + companyName);
                Console.WriteLine("3. Always Allow a la app");
                Console.WriteLine("Esperando hasta 3 minutos...");
                Console.WriteLine();

                for (int i = 0; i < 36; i++)
                {
                    Thread.Sleep(5000);
                    auth = session.RequestAccess(companyId);
                    Console.WriteLine("  Reintento " + (i + 1) + "/36 -> " + auth);
                    if (auth == AuthorizationResult.Granted || auth == AuthorizationResult.Denied)
                        break;
                }
            }

            return auth;
        }

        private static void WaitBeforeExit()
        {
            Console.WriteLine();
            Console.WriteLine("Presione Enter para cerrar...");
            try { Console.ReadLine(); } catch { }
        }
    }
}
