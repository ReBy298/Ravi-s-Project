partition Returned = m
  mode: import
  source =
    let
      Source = Sql.Databases("ENCDXPUSALT0101"),
      srcSource = Source{{[Name="Demo Tableau"]}}[Data],
      Returned_object = srcSource{{[Item="Returned",Schema="dbo"]}}[Data]
    in
      Returned_object
