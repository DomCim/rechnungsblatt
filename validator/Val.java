import org.mustangproject.validator.ZUGFeRDValidator;

/**
 * Wrapper um den Mustangproject-Validator (die shaded Jar hat kein
 * Main-Manifest). Gibt das Prüfergebnis als XML auf stdout aus.
 *
 * Kompilieren/Aufrufen:
 *   javac -cp validator.jar Val.java
 *   java  -cp .:validator.jar Val rechnung.pdf
 */
public class Val {
  public static void main(String[] a) throws Exception {
    System.out.println(new ZUGFeRDValidator().validate(a[0]));
  }
}
