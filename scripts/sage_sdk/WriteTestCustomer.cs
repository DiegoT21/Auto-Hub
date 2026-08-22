/*
 * Prueba de ESCRITURA Sage 50 SDK - SOLO empresa de prueba.
 * Crea un cliente marcador: AUTOHUB-TEST (se puede borrar a mano en Sage).
 * Copia campos de cuenta GL por reflexion (nombres cambian segun version SDK).
 */
using System;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading;
using Sage.Peachtree.API;

namespace AutoHub.SageWriteProbe
{
    internal static class Program
    {
        private const string DefaultCompany = "LYL CONSTRUCTIONS SUPPLY INC 2025-2026";
        private const string TestCustomerId = "AUTOHUB-TEST";
        private const string TestCustomerName = "AUTO-HUB PRUEBA SDK - BORRAR";

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
            var targetName = args.Length > 0 ? args[0] : DefaultCompany;
            var appId = Environment.GetEnvironmentVariable("SAGE_APP_ID") ?? "";
            if (args.Length > 1)
                appId = args[1];

            Console.WriteLine("Auto-Hub - prueba ESCRITURA Sage 50 SDK");
            Console.WriteLine("Empresa objetivo: " + targetName);
            Console.WriteLine("Accion: crear cliente " + TestCustomerId);
            Console.WriteLine("SOLO usar en empresa de PRUEBA.");
            if (appId == null || appId.Trim().Length == 0)
            {
                Console.WriteLine("ERROR: falta Application ID.");
                WaitBeforeExit();
                return 13;
            }
            Console.WriteLine("Application ID: (configurado, " + appId.Length + " chars)");
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

                Customer template = null;
                var list = company.Factories.CustomerFactory.List();
                list.Load();
                Console.WriteLine("Clientes actuales (muestra):");
                int n = 0;
                foreach (Customer c in list)
                {
                    Console.WriteLine("  - " + c.ID + " | " + c.Name);
                    if (template == null)
                        template = c;
                    if (++n >= 10) break;
                }
                Console.WriteLine();

                if (template == null)
                {
                    Console.WriteLine("ERROR: no hay cliente plantilla.");
                    WaitBeforeExit();
                    return 3;
                }

                Console.WriteLine("Plantilla GL: " + template.ID);
                Console.WriteLine("  UsualSalesAccountReference: " +
                    (template.UsualSalesAccountReference == null ? "(null)" : template.UsualSalesAccountReference.ToString()));
                Console.WriteLine("  CashAccountReference: " +
                    (template.CashAccountReference == null ? "(null)" : template.CashAccountReference.ToString()));
                Console.WriteLine();

                Console.WriteLine("Creando cliente de prueba...");
                Customer customer = company.Factories.CustomerFactory.Create();
                customer.ID = TestCustomerId;
                customer.Name = TestCustomerName;

                // Nombre real en Sage 50 2024 API (no SalesAccountReference)
                if (template.UsualSalesAccountReference == null)
                {
                    Console.WriteLine("ERROR: el cliente plantilla no tiene UsualSalesAccountReference.");
                    WaitBeforeExit();
                    return 4;
                }

                customer.UsualSalesAccountReference = template.UsualSalesAccountReference;
                Console.WriteLine("  UsualSalesAccountReference asignado.");

                if (template.CashAccountReference != null)
                {
                    customer.CashAccountReference = template.CashAccountReference;
                    Console.WriteLine("  CashAccountReference asignado.");
                }

                if (template.Terms != null)
                {
                    try
                    {
                        customer.Terms = template.Terms;
                        Console.WriteLine("  Terms asignado.");
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine("  AVISO Terms: " + ex.Message);
                    }
                }

                // Sage exige contacto: Last name, Company name o Address line 1
                try
                {
                    if (customer.BillToContact == null && template.BillToContact != null)
                    {
                        // Algunos SDK crean el contacto al Create(); si viene null, no forzar
                        Console.WriteLine("  AVISO: BillToContact null en cliente nuevo.");
                    }

                    if (customer.BillToContact != null)
                    {
                        SetContactCompanyOrAddress(customer.BillToContact, TestCustomerName);
                        Console.WriteLine("  BillToContact configurado.");
                    }
                    else if (template.BillToContact != null)
                    {
                        // Intentar copiar datos del contacto plantilla via propiedades comunes
                        CopyContactBasics(template.BillToContact, customer, TestCustomerName);
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine("  AVISO contacto: " + ex.Message);
                }

                // Fallback directo por reflexion si Save sigue pidiendo contacto
                EnsureContactMinimum(customer, TestCustomerName);

                customer.Save();
                Console.WriteLine("OK - Cliente guardado en Sage:");
                Console.WriteLine("  ID:   " + TestCustomerId);
                Console.WriteLine("  Name: " + TestCustomerName);
                Console.WriteLine();
                Console.WriteLine("Verificalo en Sage: Customers & Sales -> Customers");
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

        private static void SetContactCompanyOrAddress(Contact contact, string companyName)
        {
            // Intentar propiedades tipicas del Contact en Sage 50 US
            TrySetString(contact, "CompanyName", companyName);
            TrySetString(contact, "Name", companyName);
            TrySetString(contact, "LastName", "PRUEBA");
            TrySetString(contact, "FirstName", "AUTO-HUB");
            TrySetString(contact, "Address1", "PRUEBA SDK AUTO-HUB");
            TrySetString(contact, "AddressLine1", "PRUEBA SDK AUTO-HUB");
            TrySetString(contact, "City", "PANAMA");
        }

        private static void EnsureContactMinimum(Customer customer, string companyName)
        {
            try
            {
                var billTo = typeof(Customer).GetProperty("BillToContact");
                if (billTo == null) return;
                object contact = billTo.GetValue(customer, null);
                if (contact == null) return;
                SetContactCompanyOrAddress((Contact)contact, companyName);
            }
            catch (Exception ex)
            {
                Console.WriteLine("  AVISO EnsureContact: " + ex.Message);
            }
        }

        private static void CopyContactBasics(Contact source, Customer target, string companyName)
        {
            try
            {
                if (target.BillToContact != null)
                {
                    SetContactCompanyOrAddress(target.BillToContact, companyName);
                    // Copiar address del plantilla si existe
                    TryCopyString(source, target.BillToContact, "Address1");
                    TryCopyString(source, target.BillToContact, "AddressLine1");
                    TryCopyString(source, target.BillToContact, "City");
                    Console.WriteLine("  BillToContact desde plantilla + nombre prueba.");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("  AVISO CopyContact: " + ex.Message);
            }
        }

        private static void TrySetString(object obj, string propertyName, string value)
        {
            try
            {
                var p = obj.GetType().GetProperty(propertyName);
                if (p == null || !p.CanWrite) return;
                if (p.PropertyType != typeof(string)) return;
                p.SetValue(obj, value, null);
                Console.WriteLine("    Contact." + propertyName + " = " + value);
            }
            catch { }
        }

        private static void TryCopyString(object source, object target, string propertyName)
        {
            try
            {
                var ps = source.GetType().GetProperty(propertyName);
                var pt = target.GetType().GetProperty(propertyName);
                if (ps == null || pt == null || !pt.CanWrite) return;
                object val = ps.GetValue(source, null);
                if (val == null) return;
                pt.SetValue(target, val, null);
            }
            catch { }
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
                Console.WriteLine("2. Abre LYL CONSTRUCTIONS SUPPLY INC 2025-2026");
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
            Console.WriteLine();
            Console.WriteLine("Presione Enter para cerrar...");
            try { Console.ReadLine(); } catch { }
        }
    }
}
