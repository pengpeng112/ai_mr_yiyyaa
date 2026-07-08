import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;

public class TestVastbaseJdbc {
    public static void main(String[] args) throws Exception {
        Class.forName("org.postgresql.Driver");
        String url = args.length > 0 ? args[0] : System.getenv("MED_AUDIT_VASTBASE_JDBC_URL");
        String user = System.getenv("MED_AUDIT_VASTBASE_USER");
        String password = System.getenv("MED_AUDIT_VASTBASE_PASSWORD");
        if (url == null || user == null || password == null) {
            throw new IllegalStateException("Set MED_AUDIT_VASTBASE_JDBC_URL, MED_AUDIT_VASTBASE_USER and MED_AUDIT_VASTBASE_PASSWORD before running this diagnostic script.");
        }
        System.out.println("url=" + url);
        try (Connection conn = DriverManager.getConnection(url, user, password)) {
            System.out.println("JDBC OK");
            try (Statement stmt = conn.createStatement()) {
                ResultSet rs = stmt.executeQuery("SELECT patient_id, visit_id, progress_type_name FROM jhemr.v_blws WHERE patient_id='00018069' LIMIT 5");
                int count = 0;
                while (rs.next()) {
                    count++;
                    System.out.println(rs.getString(1) + " | " + rs.getString(2) + " | " + rs.getString(3));
                }
                System.out.println("rows=" + count);
            }
        }
    }
}
