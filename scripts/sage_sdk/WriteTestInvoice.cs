/*
 * Prueba de ESCRITURA Sage 50 SDK US - factura de prueba.
 * SOLO empresa: LYL CONST CIA de PRUEBA
 * Cliente forzado: AUTOHUB-TEST
 * Lee sample_invoice.json (shape outbox: [{sentAt, record}, ...])
 *
 * Prefijo AH-TEST- en ReferenceNumber / nota para poder localizar y borrar.
 * Si el factory/API de SalesInvoice difiere por version, vuelca metodos/props
 * por reflexion (misma tactica que UsualSalesAccountReference en el write de cliente).
 */
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using Sage.Peachtree.API;

namespace AutoHub.SageInvoiceProbe
{
    internal static class Program
    {
        private const string DefaultCompany = "LYL CONST CIA de PRUEBA";
        // Cliente real de la empresa de prueba (AUTOHUB-TEST a veces no sirve para facturar)
        private const string TestCustomerId = "C SUAREZ TORRE 1";
        private const string DefaultSamplePath = "sample_invoice.json";
        private const string ProbeVersion = "2026-08-18-autohub";

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
            // Obligatorio: sin esto, Customer.Key / EntityReference suelen fallar
            // con E_POINTER o quedar null al correr fuera de la carpeta de Sage.
            try
            {
                // Hay dos AssemblyInitializer (API y Resolver); usar el de Resolver.
                Sage.Peachtree.API.Resolver.AssemblyInitializer.Initialize();
                Console.WriteLine("AssemblyInitializer.Initialize() OK");
            }
            catch (Exception ex)
            {
                Console.WriteLine("AVISO AssemblyInitializer: " + ex.Message);
                try
                {
                    Sage.Peachtree.API.AssemblyInitializer.Initialize();
                    Console.WriteLine("AssemblyInitializer (API) OK");
                }
                catch (Exception ex2)
                {
                    Console.WriteLine("AVISO AssemblyInitializer API: " + ex2.Message);
                }
            }

            var targetName = DefaultCompany;
            var samplePath = DefaultSamplePath;
            var appId = Environment.GetEnvironmentVariable("SAGE_APP_ID") ?? "";

            // args: [company] [appId] [sampleJson]
            // o solo [sampleJson] si el primer arg termina en .json
            if (args.Length >= 1)
            {
                if (args[0].EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                    samplePath = args[0];
                else
                    targetName = args[0];
            }
            if (args.Length >= 2 && !args[0].EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                appId = args[1];
            if (args.Length >= 3)
                samplePath = args[2];
            else if (args.Length == 2 && args[0].EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                appId = args[1];

            Console.WriteLine("Auto-Hub - prueba ESCRITURA factura Sage 50 SDK (US)");
            Console.WriteLine("VERSION: " + ProbeVersion);
            Console.WriteLine("Empresa objetivo: " + targetName);
            Console.WriteLine("Cliente Sage:     " + TestCustomerId);
            Console.WriteLine("Sample JSON:      " + samplePath);
            Console.WriteLine("SOLO usar en empresa de PRUEBA.");
            Console.WriteLine("Fuente CS:        " + typeof(Program).Assembly.Location);
            if (string.IsNullOrWhiteSpace(appId))
            {
                Console.WriteLine("ERROR: falta Application ID.");
                WaitBeforeExit();
                return 13;
            }
            Console.WriteLine("Application ID: (configurado, " + appId.Length + " chars)");
            Console.WriteLine();

            List<Dictionary<string, object>> records;
            try
            {
                records = LoadInvoiceRecords(samplePath);
            }
            catch (Exception ex)
            {
                Console.WriteLine("ERROR leyendo sample: " + ex.Message);
                WaitBeforeExit();
                return 14;
            }

            if (records.Count == 0)
            {
                Console.WriteLine("ERROR: sample sin lineas de factura.");
                WaitBeforeExit();
                return 15;
            }

            var first = records[0];
            var numeroOrigen = GetString(first, "numero_factura") ?? "SIN-NUM";
            var fechaOrigen = ParseDate(GetString(first, "fecha_emision")) ?? DateTime.Today;
            // Sage exige fecha dentro de un ano contable ABIERTO. PsKloud 2023-12-29
            // suele estar cerrado en la empresa de prueba -> usar hoy.
            var fechaEmision = DateTime.Today;
            // Sage ReferenceNumber suele ser corto; AH + yyyyMMddHHmmss = 16 chars
            var refNumber = "AH" + DateTime.Now.ToString("yyyyMMddHHmmss", CultureInfo.InvariantCulture);
            if (refNumber.Length > 20)
                refNumber = refNumber.Substring(0, 20);

            Console.WriteLine("Factura origen PsKloud: " + numeroOrigen +
                " (factura_id=" + GetString(first, "factura_id") + ", lineas=" + records.Count + ")");
            Console.WriteLine("Fecha emision origen:  " + fechaOrigen.ToString("yyyy-MM-dd") +
                " (ano posiblemente cerrado)");
            Console.WriteLine("Fecha en Sage (prueba): " + fechaEmision.ToString("yyyy-MM-dd") + " <- hoy");
            Console.WriteLine("ReferenceNumber Sage:  " + refNumber);
            Console.WriteLine("Nota: AH-TEST factura PsKloud " + numeroOrigen);
            Console.WriteLine();

            PeachtreeSession session = null;
            Company company = null;

            try
            {
                session = new PeachtreeSession();
                session.Begin(appId);
                Console.WriteLine("Sesion iniciada: " + session.SessionActive);

                var companies = session.CompanyList();
                var companyId = companies.Cast<CompanyIdentifier>()
                    .FirstOrDefault(c => CompanyNamesEqual(c.CompanyName, targetName));

                if (companyId == null)
                {
                    Console.WriteLine("ERROR: No se encontro la empresa: " + targetName);
                    WaitBeforeExit();
                    return 1;
                }

                var auth = WaitForGrant(session, companyId);
                if (auth != AuthorizationResult.Granted)
                {
                    Console.WriteLine("ERROR: sin autorizacion Granted. Estado: " + auth);
                    WaitBeforeExit();
                    return 2;
                }

                company = session.Open(companyId);
                Console.WriteLine("Empresa abierta via SDK.");
                Console.WriteLine();

                Customer customer = FindCustomerById(company, TestCustomerId);
                if (customer == null)
                {
                    Console.WriteLine("ERROR: no existe cliente " + TestCustomerId +
                        ". Verifica el ID exacto en Sage (Customers).");
                    WaitBeforeExit();
                    return 3;
                }

                Console.WriteLine("Cliente Sage: " + customer.ID + " | " + customer.Name);
                Console.WriteLine("  IsInactive=" + GetProp(customer, "IsInactive") +
                    " IsProspect=" + GetProp(customer, "IsProspect"));

                object salesAcctRef = null;
                try
                {
                    salesAcctRef = customer.UsualSalesAccountReference;
                }
                catch (Exception ex)
                {
                    Console.WriteLine("AVISO UsualSalesAccountReference: " + ex.Message);
                }
                if (salesAcctRef == null)
                {
                    Console.WriteLine("ERROR: " + TestCustomerId + " no tiene UsualSalesAccountReference (GL ventas).");
                    WaitBeforeExit();
                    return 4;
                }
                Console.WriteLine("  UsualSalesAccountReference: " + salesAcctRef);
                Console.WriteLine();

                object invoice = CreateSalesInvoice(company);
                if (invoice == null)
                {
                    WaitBeforeExit();
                    return 5;
                }

                if (!AssignCustomerToInvoice(company, invoice, customer))
                {
                    Console.WriteLine("ERROR: no se pudo asignar el cliente a la factura.");
                    DumpTypeMembers(invoice.GetType(), "SalesInvoice (customer props)");
                    WaitBeforeExit();
                    return 8;
                }

                TrySetProp(invoice, "Date", fechaEmision);
                TrySetProp(invoice, "TransactionDate", fechaEmision);
                // Algunas builds usan DatePosted / ShipDate
                TrySetProp(invoice, "DatePosted", fechaEmision);
                TrySetProp(invoice, "ShipDate", fechaEmision);
                Console.WriteLine("  Date/TransactionDate = " + fechaEmision.ToString("yyyy-MM-dd"));
                TrySetStringProp(invoice, "ReferenceNumber", refNumber);
                TrySetStringProp(invoice, "InvoiceNumber", refNumber);
                TrySetStringProp(invoice, "Number", refNumber);

                var note = "AH-TEST PsKloud " + numeroOrigen + " id=" + GetString(first, "factura_id");
                TrySetStringProp(invoice, "Note", note);
                TrySetStringProp(invoice, "InternalNote", note);
                TrySetStringProp(invoice, "Memo", note);
                Console.WriteLine("  Fecha / referencia / nota configurados.");

                int lineNo = 0;
                foreach (var rec in records)
                {
                    lineNo++;
                    object line = AddInvoiceLine(invoice, company);
                    if (line == null)
                    {
                        Console.WriteLine("ERROR: no se pudo crear linea " + lineNo);
                        DumpTypeMembers(invoice.GetType(), "Invoice (para AddLine)");
                        WaitBeforeExit();
                        return 6;
                    }

                    var desc = GetString(rec, "descripcion") ?? ("Linea " + lineNo);
                    var qty = ParseDecimal(GetString(rec, "cantidad")) ?? 1m;
                    var price = ParseDecimal(GetString(rec, "precio_unitario")) ?? 0m;
                    var amount = ParseDecimal(GetString(rec, "total_linea")) ?? (qty * price);

                    TrySetStringProp(line, "Description", desc);
                    TrySetProp(line, "Quantity", qty);
                    TrySetProp(line, "QuantitySold", qty);
                    TrySetProp(line, "UnitPrice", price);
                    TrySetProp(line, "Amount", amount);
                    TrySetProp(line, "AccountReference", salesAcctRef);
                    TrySetProp(line, "GLAccountReference", salesAcctRef);
                    // Sin inventory item: linea de GL / description-only
                    TrySetProp(line, "IsInventory", false);

                    Console.WriteLine("  Linea " + lineNo + ": qty=" + qty +
                        " price=" + price + " | " + Truncate(desc, 60));
                }

                Console.WriteLine();
                Console.WriteLine("Guardando factura...");
                if (!InvokeSave(invoice))
                {
                    Console.WriteLine("ERROR: Save() fallo o no existe en " + invoice.GetType().Name);
                    DumpTypeMembers(invoice.GetType(), "SalesInvoice (Save)");
                    WaitBeforeExit();
                    return 7;
                }
                Console.WriteLine("OK - Factura guardada");
                Console.WriteLine("  Reference: " + refNumber);
                Console.WriteLine("  Cliente:   " + TestCustomerId);
                Console.WriteLine("  Lineas:    " + records.Count);
                Console.WriteLine();
                Console.WriteLine("Verificalo en Sage: Customers & Sales -> Sales Invoices");
                Console.WriteLine("Busca prefijo AH / nota AH-TEST (se puede borrar a mano).");
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

        private static object CreateSalesInvoice(Company company)
        {
            Console.WriteLine("Creando SalesInvoice via factory...");
            object factories = GetProp(company, "Factories");
            if (factories == null)
            {
                Console.WriteLine("ERROR: company.Factories es null.");
                return null;
            }

            // Nombres tipicos US API
            string[] factoryNames =
            {
                "SalesInvoiceFactory",
                "SalesJournalFactory",
                "InvoiceFactory"
            };

            object factory = null;
            string usedName = null;
            foreach (var name in factoryNames)
            {
                factory = GetProp(factories, name);
                if (factory != null)
                {
                    usedName = name;
                    break;
                }
            }

            if (factory == null)
            {
                Console.WriteLine("ERROR: no hay SalesInvoiceFactory en Factories.");
                DumpTypeMembers(factories.GetType(), "Factories");
                return null;
            }

            Console.WriteLine("  Factory: " + usedName + " (" + factory.GetType().Name + ")");

            object invoice = InvokeMethod(factory, "Create");
            if (invoice == null)
                invoice = InvokeMethod(factory, "CreateSalesInvoice");
            if (invoice == null)
                invoice = InvokeMethod(factory, "NewSalesInvoice");

            if (invoice == null)
            {
                // Ultimo recurso: ctor publico sin args del tipo SalesInvoice
                var asm = typeof(Customer).Assembly;
                var invType = asm.GetType("Sage.Peachtree.API.SalesInvoice")
                    ?? Array.Find(asm.GetTypes(), t => t.Name == "SalesInvoice");
                if (invType != null)
                {
                    try
                    {
                        invoice = Activator.CreateInstance(invType);
                        Console.WriteLine("  Instanciado SalesInvoice via Activator.");
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine("  Activator fallo: " + ex.Message);
                    }
                }
            }

            if (invoice == null)
            {
                Console.WriteLine("ERROR: no se pudo Create() SalesInvoice.");
                DumpTypeMembers(factory.GetType(), usedName);
                return null;
            }

            Console.WriteLine("  Invoice tipo: " + invoice.GetType().FullName);
            return invoice;
        }

        private static object AddInvoiceLine(object invoice, Company company)
        {
            // Preferir metodos de instancia tipo AddLine / AddSalesLine
            string[] methodNames =
            {
                "AddLine",
                "AddSalesLine",
                "AddDistribution",
                "AddSalesInvoiceLine",
                "CreateLine"
            };
            foreach (var m in methodNames)
            {
                var line = InvokeMethod(invoice, m);
                if (line != null)
                    return line;
            }

            // Coleccion Lines / SalesLines / Distributions
            string[] collNames = { "Lines", "SalesLines", "Distributions", "LineItems", "RowCollection" };
            foreach (var cname in collNames)
            {
                var coll = GetProp(invoice, cname);
                if (coll == null) continue;

                var added = InvokeMethod(coll, "Add");
                if (added != null) return added;

                // Add() sin retorno: crear linea con factory y Add(line)
                object lineFactory = null;
                var factories = GetProp(company, "Factories");
                if (factories != null)
                {
                    lineFactory = GetProp(factories, "SalesInvoiceLineFactory")
                        ?? GetProp(factories, "SalesLineFactory");
                }
                object newLine = null;
                if (lineFactory != null)
                    newLine = InvokeMethod(lineFactory, "Create");

                if (newLine == null)
                {
                    var asm = invoice.GetType().Assembly;
                    var lineType = Array.Find(asm.GetTypes(),
                        t => t.Name == "SalesInvoiceLine" || t.Name == "SalesLine");
                    if (lineType != null)
                    {
                        try { newLine = Activator.CreateInstance(lineType); }
                        catch { }
                    }
                }

                if (newLine != null)
                {
                    if (InvokeMethod(coll, "Add", newLine) != null || TryCollectionAdd(coll, newLine))
                        return newLine;
                }
            }

            return null;
        }

        private static bool TryCollectionAdd(object coll, object item)
        {
            try
            {
                var m = coll.GetType().GetMethod("Add", new[] { item.GetType() })
                    ?? coll.GetType().GetMethods()
                        .FirstOrDefault(x => x.Name == "Add" && x.GetParameters().Length == 1);
                if (m == null) return false;
                m.Invoke(coll, new[] { item });
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static Customer FindCustomerById(Company company, string id)
        {
            try
            {
                var list = company.Factories.CustomerFactory.List();
                TryLoadCustomerListFiltered(list, id);
                foreach (Customer c in list)
                {
                    if (string.Equals(c.ID, id, StringComparison.OrdinalIgnoreCase))
                        return c;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("AVISO FindCustomer filtro: " + ex.Message);
            }

            // Fallback: lista completa
            try
            {
                var list = company.Factories.CustomerFactory.List();
                list.Load();
                foreach (Customer c in list)
                {
                    if (string.Equals(c.ID, id, StringComparison.OrdinalIgnoreCase))
                        return c;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("AVISO FindCustomer lista: " + ex.Message);
            }

            return null;
        }

        /// <summary>
        /// Lee Customer.Key tipado (no via GetProp que traga excepciones).
        /// </summary>
        private static object ReadCustomerKey(Customer customer)
        {
            try
            {
                object key = customer.Key;
                Console.WriteLine("  Customer.Key tipo: " +
                    (key == null ? "(null)" : key.GetType().FullName));
                Console.WriteLine("  Customer.Key valor: " + (key == null ? "(null)" : key.ToString()));
                return key;
            }
            catch (Exception ex)
            {
                Console.WriteLine("  ERROR leyendo Customer.Key: " + ex.GetType().Name + " - " + ex.Message);
                if (ex.InnerException != null)
                    Console.WriteLine("    Inner: " + ex.InnerException.Message);
                return null;
            }
        }

        /// <summary>
        /// Asigna el cliente a SalesInvoice. El error "The customer can't be found"
        /// suele ser CustomerReference vacio/mal tipado (no basta con el string ID).
        /// </summary>
        private static bool AssignCustomerToInvoice(Company company, object invoice, Customer customer)
        {
            object key = ReadCustomerKey(customer);

            // Si Key sigue null, re-cargar el cliente (lista filtrada / factory.Load)
            if (key == null)
            {
                Console.WriteLine("  Reintentando carga de cliente para obtener Key...");
                var reloaded = ReloadCustomerWithKey(company, customer.ID);
                if (reloaded != null)
                {
                    customer = reloaded;
                    key = ReadCustomerKey(customer);
                }
            }

            if (key == null)
            {
                Console.WriteLine("  Dump props Customer (Key ausente):");
                DumpTypeMembers(customer.GetType(), "Customer");
                try
                {
                    DumpTypeMembers(company.Factories.CustomerFactory.GetType(), "CustomerFactory");
                }
                catch { }
            }

            var refProp = invoice.GetType().GetProperty("CustomerReference",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase);
            if (refProp != null)
                Console.WriteLine("  Invoice.CustomerReference tipo prop: " + refProp.PropertyType.FullName);

            // 1) Tipado: SalesInvoice.CustomerReference = customer.Key
            var salesInv = invoice as SalesInvoice;
            if (salesInv != null && key != null)
            {
                try
                {
                    var crProp = typeof(SalesInvoice).GetProperty("CustomerReference");
                    if (crProp != null && crProp.CanWrite)
                    {
                        crProp.SetValue(salesInv, key, null);
                        var after = crProp.GetValue(salesInv, null);
                        Console.WriteLine("  CustomerReference (SalesInvoice tipado) OK -> " + after);
                        if (after != null) return true;
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine("  AVISO set tipado SalesInvoice: " + ex.Message);
                    if (ex.InnerException != null)
                        Console.WriteLine("    Inner: " + ex.InnerException.Message);
                }
            }

            // 2) Reflexion: invoice.CustomerReference = key
            if (refProp != null && refProp.CanWrite && key != null)
            {
                try
                {
                    if (refProp.PropertyType.IsAssignableFrom(key.GetType()))
                    {
                        refProp.SetValue(invoice, key, null);
                        var after = refProp.GetValue(invoice, null);
                        Console.WriteLine("  CustomerReference = customer.Key OK -> " + after);
                        if (after != null) return true;
                    }
                    else
                    {
                        // Intento Convert / cast via ChangeType no aplica; probar SetValue igual
                        Console.WriteLine("  AVISO: Key tipo " + key.GetType().FullName +
                            " vs prop " + refProp.PropertyType.FullName + " - intento SetValue igual");
                        refProp.SetValue(invoice, key, null);
                        var after = refProp.GetValue(invoice, null);
                        Console.WriteLine("  CustomerReference SetValue -> " + after);
                        if (after != null) return true;
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine("  AVISO set CustomerReference(Key): " + ex.Message);
                    if (ex.InnerException != null)
                        Console.WriteLine("    Inner: " + ex.InnerException.Message);
                }
            }

            // 3) CustomerFactory.CreateReference / GetEntityReference / Load
            object custFactory = company.Factories.CustomerFactory;
            string[] refMethods = { "CreateReference", "GetEntityReference", "FetchEntityReference", "GetReference" };
            foreach (var mname in refMethods)
            {
                object createdRef = null;
                if (key != null)
                    createdRef = InvokeMethod(custFactory, mname, key);
                if (createdRef == null)
                    createdRef = InvokeMethod(custFactory, mname, customer.ID);

                if (createdRef != null && refProp != null && refProp.CanWrite)
                {
                    try
                    {
                        refProp.SetValue(invoice, createdRef, null);
                        Console.WriteLine("  CustomerReference via " + mname + " OK -> " +
                            refProp.GetValue(invoice, null));
                        return true;
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine("  AVISO " + mname + ": " + ex.Message);
                    }
                }
            }

            // 4) Factory.Load(string id) -> usar Key del resultado
            foreach (var m in custFactory.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public))
            {
                if (!string.Equals(m.Name, "Load", StringComparison.OrdinalIgnoreCase)) continue;
                var ps = m.GetParameters();
                if (ps.Length != 1) continue;
                try
                {
                    object loaded = null;
                    if (ps[0].ParameterType == typeof(string))
                        loaded = m.Invoke(custFactory, new object[] { customer.ID });
                    else if (key != null && ps[0].ParameterType.IsAssignableFrom(key.GetType()))
                        loaded = m.Invoke(custFactory, new object[] { key });
                    var loadedCust = loaded as Customer;
                    if (loadedCust == null) continue;
                    object loadedKey = ReadCustomerKey(loadedCust);
                    if (loadedKey != null && refProp != null && refProp.CanWrite)
                    {
                        refProp.SetValue(invoice, loadedKey, null);
                        Console.WriteLine("  CustomerReference via Factory.Load OK -> " +
                            refProp.GetValue(invoice, null));
                        return true;
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine("  AVISO Factory.Load: " + ex.Message);
                }
            }

            // 5) Ultimo recurso: string ID (casi nunca alcanza para Save)
            if (TrySetStringProp(invoice, "CustomerID", customer.ID))
            {
                Console.WriteLine("  Fallback CustomerID string = " + customer.ID);
                if (refProp != null)
                {
                    var cur = refProp.GetValue(invoice, null);
                    Console.WriteLine("  CustomerReference ahora: " + (cur == null ? "(null)" : cur.ToString()));
                    return cur != null;
                }
            }

            return false;
        }

        private static Customer ReloadCustomerWithKey(Company company, string id)
        {
            try
            {
                var list = company.Factories.CustomerFactory.List();
                TryLoadCustomerListFiltered(list, id);
                foreach (Customer c in list)
                {
                    if (!string.Equals(c.ID, id, StringComparison.OrdinalIgnoreCase))
                        continue;
                    try
                    {
                        if (c.Key != null) return c;
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine("  AVISO Key en reload: " + ex.Message);
                    }
                    return c;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("  AVISO ReloadCustomer: " + ex.Message);
            }
            return null;
        }

        private static void TryLoadCustomerListFiltered(object list, string id)
        {
            try
            {
                var asm = typeof(Customer).Assembly;
                var modifiersType = asm.GetType("Sage.Peachtree.API.LoadModifiers");
                var filterExprType = asm.GetType("Sage.Peachtree.API.FilterExpression");
                if (modifiersType == null || filterExprType == null)
                {
                    // Buscar en todos los assemblies ya cargados (post-AssemblyInitializer)
                    foreach (var a in AppDomain.CurrentDomain.GetAssemblies())
                    {
                        if (modifiersType == null)
                            modifiersType = a.GetType("Sage.Peachtree.API.LoadModifiers");
                        if (filterExprType == null)
                            filterExprType = a.GetType("Sage.Peachtree.API.FilterExpression");
                    }
                }

                Console.WriteLine("  LoadModifiers type: " +
                    (modifiersType == null ? "(null)" : modifiersType.Assembly.GetName().Name));
                Console.WriteLine("  FilterExpression type: " +
                    (filterExprType == null ? "(null)" : filterExprType.Assembly.GetName().Name));

                object modifiers = null;
                if (modifiersType != null)
                {
                    var create = modifiersType.GetMethod("Create", Type.EmptyTypes)
                        ?? modifiersType.GetMethod("Create", BindingFlags.Public | BindingFlags.Static);
                    if (create != null)
                        modifiers = create.Invoke(null, null);
                }

                MethodInfo propMethod = null, constMethod = null, equalMethod = null;
                if (filterExprType != null)
                {
                    propMethod = filterExprType.GetMethod("Property", new[] { typeof(string) });
                    constMethod = filterExprType.GetMethods()
                        .FirstOrDefault(m => m.Name == "Constant" && m.GetParameters().Length == 1);
                    equalMethod = filterExprType.GetMethods()
                        .FirstOrDefault(m => m.Name == "Equal" && m.GetParameters().Length == 2);
                }

                if (modifiers != null && propMethod != null && constMethod != null && equalMethod != null)
                {
                    object left = propMethod.Invoke(null, new object[] { "Customer.ID" });
                    object right = constMethod.IsGenericMethod
                        ? constMethod.MakeGenericMethod(typeof(string)).Invoke(null, new object[] { id })
                        : constMethod.Invoke(null, new object[] { id });
                    object filter = equalMethod.Invoke(null, new[] { left, right });
                    var filtersProp = modifiers.GetType().GetProperty("Filters");
                    if (filtersProp != null && filtersProp.CanWrite)
                        filtersProp.SetValue(modifiers, filter, null);

                    var load = list.GetType().GetMethod("Load", new[] { modifiers.GetType() })
                        ?? list.GetType().GetMethod("Load", new[] { modifiersType });
                    if (load != null)
                    {
                        load.Invoke(list, new[] { modifiers });
                        Console.WriteLine("  List.Load(LoadModifiers) OK");
                        return;
                    }
                }

                var loadPlain = list.GetType().GetMethod("Load", Type.EmptyTypes);
                if (loadPlain != null)
                    loadPlain.Invoke(list, null);
            }
            catch (Exception ex)
            {
                Console.WriteLine("  AVISO TryLoadCustomerListFiltered: " + ex.Message);
                try
                {
                    var loadPlain = list.GetType().GetMethod("Load", Type.EmptyTypes);
                    if (loadPlain != null)
                        loadPlain.Invoke(list, null);
                }
                catch { }
            }
        }

        private static List<Dictionary<string, object>> LoadInvoiceRecords(string path)
        {
            if (!Path.IsPathRooted(path))
                path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, path);
            if (!File.Exists(path))
                throw new FileNotFoundException("No existe: " + path, path);

            var text = File.ReadAllText(path);
            var ser = new JavaScriptSerializer();
            var root = ser.DeserializeObject(text);

            var records = new List<Dictionary<string, object>>();

            // Shape A: [ {sentAt, record}, ... ]  (outbox-compatible)
            var arr = root as object[];
            if (arr != null)
            {
                foreach (var item in arr)
                {
                    var env = AsDict(item);
                    if (env == null) continue;
                    if (env.ContainsKey("record"))
                    {
                        var rec = AsDict(env["record"]);
                        if (rec != null) records.Add(rec);
                    }
                    else if (env.ContainsKey("factura_id") || env.ContainsKey("descripcion"))
                    {
                        records.Add(env);
                    }
                }
                return records;
            }

            // Shape B: { sentAt, records: [ ... ] }  (ingest HTTP)
            var dict = AsDict(root);
            if (dict != null && dict.ContainsKey("records"))
            {
                var recArr = dict["records"] as object[];
                if (recArr != null)
                {
                    foreach (var item in recArr)
                    {
                        var rec = AsDict(item);
                        if (rec != null) records.Add(rec);
                    }
                }
                return records;
            }

            // Shape C: un solo {sentAt, record}
            if (dict != null && dict.ContainsKey("record"))
            {
                var rec = AsDict(dict["record"]);
                if (rec != null) records.Add(rec);
                return records;
            }

            throw new InvalidDataException(
                "JSON no reconocido. Esperado array outbox [{sentAt,record},...] o {records:[...]}.");
        }

        private static Dictionary<string, object> AsDict(object obj)
        {
            if (obj == null) return null;
            var d = obj as Dictionary<string, object>;
            if (d != null) return d;

            // JavaScriptSerializer a veces usa Dictionary<string, object> ya;
            // IDictionary generico:
            var id = obj as IDictionary;
            if (id != null)
            {
                var copy = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
                foreach (DictionaryEntry e in id)
                    copy[Convert.ToString(e.Key)] = e.Value;
                return copy;
            }
            return null;
        }

        private static string GetString(Dictionary<string, object> rec, string key)
        {
            object val;
            if (!rec.TryGetValue(key, out val) || val == null) return null;
            return Convert.ToString(val, CultureInfo.InvariantCulture);
        }

        private static decimal? ParseDecimal(string s)
        {
            if (string.IsNullOrWhiteSpace(s)) return null;
            decimal d;
            if (decimal.TryParse(s, NumberStyles.Any, CultureInfo.InvariantCulture, out d))
                return d;
            if (decimal.TryParse(s, NumberStyles.Any, CultureInfo.CurrentCulture, out d))
                return d;
            return null;
        }

        private static DateTime? ParseDate(string s)
        {
            if (string.IsNullOrWhiteSpace(s)) return null;
            DateTime dt;
            if (DateTime.TryParseExact(s, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                    DateTimeStyles.None, out dt))
                return dt;
            if (DateTime.TryParse(s, CultureInfo.InvariantCulture, DateTimeStyles.AssumeLocal, out dt))
                return dt.Date;
            return null;
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

        private static bool TrySetProp(object obj, string name, object value)
        {
            if (obj == null || value == null) return false;
            try
            {
                var p = obj.GetType().GetProperty(name,
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase);
                if (p == null || !p.CanWrite) return false;

                object coerced = value;
                if (p.PropertyType != value.GetType() && value is IConvertible)
                {
                    try
                    {
                        if (p.PropertyType == typeof(decimal) || p.PropertyType == typeof(decimal?))
                            coerced = Convert.ToDecimal(value, CultureInfo.InvariantCulture);
                        else if (p.PropertyType == typeof(double) || p.PropertyType == typeof(double?))
                            coerced = Convert.ToDouble(value, CultureInfo.InvariantCulture);
                        else if (p.PropertyType == typeof(int) || p.PropertyType == typeof(int?))
                            coerced = Convert.ToInt32(value, CultureInfo.InvariantCulture);
                        else if (p.PropertyType == typeof(DateTime) || p.PropertyType == typeof(DateTime?))
                            coerced = Convert.ToDateTime(value, CultureInfo.InvariantCulture);
                        else if (p.PropertyType == typeof(string))
                            coerced = Convert.ToString(value, CultureInfo.InvariantCulture);
                        else if (p.PropertyType.IsEnum)
                            coerced = Enum.ToObject(p.PropertyType, value);
                        else
                            coerced = Convert.ChangeType(value, Nullable.GetUnderlyingType(p.PropertyType) ?? p.PropertyType, CultureInfo.InvariantCulture);
                    }
                    catch
                    {
                        // dejar value original (p.ej. EntityReference)
                        coerced = value;
                    }
                }

                p.SetValue(obj, coerced, null);
                return true;
            }
            catch (Exception ex)
            {
                Console.WriteLine("    AVISO set " + name + ": " + ex.Message);
                return false;
            }
        }

        private static bool TrySetStringProp(object obj, string name, string value)
        {
            return TrySetProp(obj, name, value);
        }

        private static object InvokeMethod(object obj, string name, params object[] args)
        {
            if (obj == null) return null;
            try
            {
                Type[] types = args == null || args.Length == 0
                    ? Type.EmptyTypes
                    : Array.ConvertAll(args, a => a == null ? typeof(object) : a.GetType());

                var m = obj.GetType().GetMethod(name, types);
                if (m == null)
                {
                    m = obj.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public)
                        .FirstOrDefault(x =>
                            x.Name.Equals(name, StringComparison.OrdinalIgnoreCase) &&
                            x.GetParameters().Length == (args == null ? 0 : args.Length));
                }
                if (m == null) return null;
                return m.Invoke(obj, args ?? new object[0]);
            }
            catch (TargetInvocationException tie)
            {
                Console.WriteLine("    AVISO " + name + "(): " +
                    (tie.InnerException != null ? tie.InnerException.Message : tie.Message));
                return null;
            }
            catch (Exception ex)
            {
                Console.WriteLine("    AVISO " + name + "(): " + ex.Message);
                return null;
            }
        }

        /// <summary>Save debe fallar ruidosamente (no tragarse la excepcion).</summary>
        private static bool InvokeSave(object invoice)
        {
            var m = invoice.GetType().GetMethod("Save", Type.EmptyTypes)
                ?? invoice.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public)
                    .FirstOrDefault(x =>
                        x.Name.Equals("Save", StringComparison.OrdinalIgnoreCase) &&
                        x.GetParameters().Length == 0);
            if (m == null)
                return false;
            try
            {
                m.Invoke(invoice, null);
                return true;
            }
            catch (TargetInvocationException tie)
            {
                var inner = tie.InnerException ?? tie;
                Console.WriteLine("ERROR Save: " + inner.Message);
                throw inner;
            }
        }

        private static void DumpTypeMembers(Type type, string label)
        {
            Console.WriteLine("--- Reflexion: " + label + " ---");
            try
            {
                var props = type.GetProperties(BindingFlags.Instance | BindingFlags.Public)
                    .Select(p => p.Name + ":" + p.PropertyType.Name)
                    .OrderBy(s => s)
                    .Take(40);
                Console.WriteLine("  Props: " + string.Join(", ", props.ToArray()));

                var methods = type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly)
                    .Where(m => !m.IsSpecialName)
                    .Select(m => m.Name + "(" + m.GetParameters().Length + ")")
                    .Distinct()
                    .OrderBy(s => s)
                    .Take(40);
                Console.WriteLine("  Methods: " + string.Join(", ", methods.ToArray()));
            }
            catch (Exception ex)
            {
                Console.WriteLine("  (dump fallo: " + ex.Message + ")");
            }
            Console.WriteLine("---");
        }

        private static string Truncate(string s, int max)
        {
            if (string.IsNullOrEmpty(s) || s.Length <= max) return s;
            return s.Substring(0, max - 3) + "...";
        }

        private static AuthorizationResult WaitForGrant(PeachtreeSession session, CompanyIdentifier companyId)
        {
            Console.WriteLine("Solicitando acceso...");
            var auth = session.RequestAccess(companyId);
            Console.WriteLine("Autorizacion: " + auth);

            if (auth == AuthorizationResult.Pending)
            {
                Console.WriteLine();
                Console.WriteLine("=== ACCION EN SAGE ===");
                Console.WriteLine("1. Close Company en Sage");
                Console.WriteLine("2. Abre LYL CONST CIA de PRUEBA");
                Console.WriteLine("3. Always Allow");
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
            var noPause = Environment.GetEnvironmentVariable("SAGE_SDK_NOPAUSE");
            if (!string.IsNullOrWhiteSpace(noPause) && noPause != "0")
                return;
            Console.WriteLine();
            Console.WriteLine("Presione Enter para cerrar...");
            try { Console.ReadLine(); } catch { }
        }
    }
}
