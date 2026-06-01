import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;

public class TestVastbaseJdbc {
    public static void main(String[] args) throws Exception {
        Class.forName("org.postgresql.Driver");
        String url = args.length > 0 ? args[0] : "jdbc:postgresql://10.10.8.177:5432/jhemr";
        System.out.println("url=" + url);
        try (Connection conn = DriverManager.getConnection(url, "aizk_user", "aizk_user@123")) {
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
