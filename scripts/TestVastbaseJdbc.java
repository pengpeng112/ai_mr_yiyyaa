import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

/** 只读 JDBC 连通性诊断：输入来自环境变量，只输出聚合计数。 */
public class TestVastbaseJdbc {
    public static void main(String[] args) throws Exception {
        String url = System.getenv("MED_AUDIT_VASTBASE_JDBC_URL");
        String user = System.getenv("MED_AUDIT_VASTBASE_USER");
        String password = System.getenv("MED_AUDIT_VASTBASE_PASSWORD");
        String patientId = System.getenv("MED_AUDIT_DEBUG_PATIENT_ID");
        if (url == null || user == null || password == null || patientId == null) {
            throw new IllegalArgumentException(
                "Set MED_AUDIT_VASTBASE_JDBC_URL, MED_AUDIT_VASTBASE_USER, " +
                "MED_AUDIT_VASTBASE_PASSWORD and MED_AUDIT_DEBUG_PATIENT_ID"
            );
        }
        Class.forName("org.postgresql.Driver");
        try (Connection conn = DriverManager.getConnection(url, user, password);
             PreparedStatement stmt = conn.prepareStatement(
                 "SELECT count(*) FROM jhemr.v_blws WHERE patient_id=?")) {
            stmt.setString(1, patientId);
            try (ResultSet rs = stmt.executeQuery()) {
                rs.next();
                System.out.println("record_count=" + rs.getLong(1));
            }
        }
    }
}
