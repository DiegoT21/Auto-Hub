/*
 * Prueba de conexion Sage 50 SDK (SOLO LECTURA - no modifica datos).
 * Compilar y ejecutar en la PC donde esta Sage 50.
 * Ver run_probe.bat en la misma carpeta.
 */
using System;
using System.Linq;
using System.Text.RegularExpressions;
using Sage.Peachtree.API;

namespace AutoHub.SageProbe
{
    internal static class Program
    {
        private const string DefaultCompany = "LYL CONSTRUCTIONS SUPPLY INC 2025-2026";

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
            // Application ID de Sage (sdk.50us@sage.com). Vacio = solo companias sample oficiales.
            var appId = Environment.GetEnvironmentVariable("SAGE_APP_ID") ?? "";
            if (args.Length > 1)
                appId = args[1];

            Console.WriteLine("Auto-Hub - prueba Sage 50 SDK (solo lectura)");
            Console.WriteLine("Empresa objetivo: " + targetName);
            if (appId == null || appId.Trim().Length == 0)
                Console.WriteLine("Application ID: (vacio - solo sample companies)");
            else
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
                Console.WriteLine("Companias registradas en Sage:");
                foreach (CompanyIdentifier id in companies)
                {
                    Console.WriteLine("  - " + id.CompanyName);
                }
                Console.WriteLine();

                var companyId = companies.FirstOrDefault(c => CompanyNamesEqual(c.CompanyName, targetName));
                if (companyId == null)
                {
                    Console.WriteLine("ERROR: No se encontro la empresa: " + targetName);
                    WaitBeforeExit();
                    return 1;
                }

                Console.WriteLine("Solicitando acceso...");
                var auth = session.RequestAccess(companyId);
                Console.WriteLine("Autorizacion: " + auth);

                if (auth == AuthorizationResult.Pending)
                {
                    Console.WriteLine();
                    Console.WriteLine("=== ACCION REQUERIDA EN SAGE 50 ===");
                    Console.WriteLine("No aparece una pestana del navegador.");
                    Console.WriteLine("El aviso sale DENTRO de Sage al abrir la empresa:");
                    Console.WriteLine("  1. Abre Sage 50.");
                    Console.WriteLine("  2. Si la empresa ya esta abierta, CIERRALA (File > Close Company).");
                    Console.WriteLine("  3. Vuelve a ABRIR: LYL CONSTRUCTIONS SUPPLY INC 2025-2026");
                    Console.WriteLine("  4. Cuando Sage pregunte Allow / Always Allow -> Always Allow");
                    Console.WriteLine("  5. Esta ventana seguira esperando hasta 3 minutos...");
                    Console.WriteLine();

                    for (int i = 0; i < 36; i++)
                    {
                        System.Threading.Thread.Sleep(5000);
                        auth = session.RequestAccess(companyId);
                        Console.WriteLine("  Reintento " + (i + 1) + "/36 -> " + auth);
                        if (auth == AuthorizationResult.Granted)
                            break;
                        if (auth == AuthorizationResult.Denied)
                            break;
                    }
                }

                if (auth != AuthorizationResult.Granted)
                {
                    Console.WriteLine();
                    Console.WriteLine("ERROR: Sage no concedio acceso. Estado: " + auth);
                    Console.WriteLine("Prueba: cerrar empresa en Sage, abrirla otra vez, Always Allow, y volver a correr.");
                    WaitBeforeExit();
                    return 2;
                }

                company = session.Open(companyId);
                Console.WriteLine("OK - Empresa abierta via SDK.");
                Console.WriteLine("Listo para leer/escribir facturas desde Auto-Hub.");
                WaitBeforeExit();
                return 0;
            }
            catch (Exception ex)
            {
                Console.WriteLine("ERROR: " + ex.Message);
                if (ex.InnerException != null)
                    Console.WriteLine("  Inner: " + ex.InnerException.Message);
                if (ex.Message.IndexOf("application identifier", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    Console.WriteLine();
                    Console.WriteLine("SOLUCION: Para empresas reales (no sample) Sage exige Application ID.");
                    Console.WriteLine("  1. Pedir ID a sdk.50us@sage.com (licencia SDK / Development Partner).");
                    Console.WriteLine("  2. Pegar el ID en app_id.txt y correr ABRIR_PRUEBA.bat");
                }
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

        private static void WaitBeforeExit()
        {
            Console.WriteLine();
            Console.WriteLine("Presione Enter para cerrar...");
            try { Console.ReadLine(); } catch { }
        }
    }
}
